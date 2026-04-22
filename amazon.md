Orders v0
Programmatically retrieve order information.

Use the Orders Selling Partner API to programmatically retrieve order information. With this API, you can develop fast, flexible, and custom applications to manage order synchronization, perform order research, and create demand-based decision support tools.

For more information, refer to:

Orders API
Orders API Rate Limits
Orders API v0 model
📘
Note

For the JP, AU, and SG marketplaces, the Orders API supports orders from 2016 onward. For all other marketplaces, the Orders API supports orders for the last two years (orders older than this don't show up in the response).


getOrders
get
deprecated
https://sellingpartnerapi-na.amazon.com/orders/v0/orders

Returns orders that are created or updated during the specified time period. If you want to return specific types of orders, you can apply filters to your request. NextToken doesn't affect any filters that you include in your request; it only impacts the pagination for the filtered orders response.

Usage Plan:

Rate (requests per second)	Burst
0.0167	20
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Query Params
CreatedAfter
string
Use this date to select orders created after (or at) a specified time. Only orders placed after the specified time are returned. The date must be in ISO 8601 format.

Note: Either the CreatedAfter parameter or the LastUpdatedAfter parameter is required. Both cannot be empty. LastUpdatedAfter and LastUpdatedBefore cannot be set when CreatedAfter is set.

CreatedBefore
string
Use this date to select orders created before (or at) a specified time. Only orders placed before the specified time are returned. The date must be in ISO 8601 format.

Note: CreatedBefore is optional when CreatedAfter is set. If specified, CreatedBefore must be equal to or after the CreatedAfter date and at least two minutes before current time.

LastUpdatedAfter
string
Use this date to select orders that were last updated after (or at) a specified time. An update is defined as any change in order status, including the creation of a new order. Includes updates made by Amazon and by the seller. The date must be in ISO 8601 format.

Note: Either the CreatedAfter parameter or the LastUpdatedAfter parameter is required. Both cannot be empty. CreatedAfter or CreatedBefore cannot be set when LastUpdatedAfter is set.

LastUpdatedBefore
string
Use this date to select orders that were last updated before (or at) a specified time. An update is defined as any change in order status, including the creation of a new order. Includes updates made by Amazon and by the seller. The date must be in ISO 8601 format.

Note: LastUpdatedBefore is optional when LastUpdatedAfter is set. But if specified, LastUpdatedBefore must be equal to or after the LastUpdatedAfter date and at least two minutes before current time.

OrderStatuses
array of strings
A list of OrderStatus values used to filter the results.

Possible values:

PendingAvailability (This status is available for pre-orders only. The order has been placed, payment has not been authorized, and the release date of the item is in the future.)
Pending (The order has been placed but payment has not been authorized.)
Unshipped (Payment has been authorized and the order is ready for shipment, but no items in the order have been shipped.)
PartiallyShipped (One or more, but not all, items in the order have been shipped.)
Shipped (All items in the order have been shipped.)
InvoiceUnconfirmed (All items in the order have been shipped. The seller has not yet given confirmation to Amazon that the invoice has been shipped to the buyer.)
Canceled (The order has been canceled.)
Unfulfillable (The order cannot be fulfilled. This state applies only to Multi-Channel Fulfillment orders.)

ADD string
MarketplaceIds
array of strings
required
length ≤ 50
A list of MarketplaceId values. Used to select orders that were placed in the specified marketplaces.

Refer to Marketplace IDs for a complete list of marketplaceId values.


ADD string
FulfillmentChannels
array of strings
A list that indicates how an order was fulfilled. Filters the results by fulfillment channel.

Possible values: AFN (fulfilled by Amazon), MFN (fulfilled by seller).


ADD string
PaymentMethods
array of strings
A list of payment method values. Use this field to select orders that were paid with the specified payment methods.

Possible values: COD (cash on delivery), CVS (convenience store), Other (Any payment method other than COD or CVS).


ADD string
SellerOrderId
string
An order identifier that is specified by the seller. Used to select only the orders that match the order identifier. If SellerOrderId is specified, then FulfillmentChannels, OrderStatuses, PaymentMethod, LastUpdatedAfter, and LastUpdatedBefore cannot be specified.

MaxResultsPerPage
integer
A number that indicates the maximum number of orders that can be returned per page. Value must be 1 - 100. Default 100.

EasyShipShipmentStatuses
array of strings
A list of EasyShipShipmentStatus values. Used to select Easy Ship orders with statuses that match the specified values. If EasyShipShipmentStatus is specified, only Amazon Easy Ship orders are returned.

Possible values:

PendingSchedule (The package is awaiting the schedule for pick-up.)
PendingPickUp (Amazon has not yet picked up the package from the seller.)
PendingDropOff (The seller will deliver the package to the carrier.)
LabelCanceled (The seller canceled the pickup.)
PickedUp (Amazon has picked up the package from the seller.)
DroppedOff (The package is delivered to the carrier by the seller.)
AtOriginFC (The packaged is at the origin fulfillment center.)
AtDestinationFC (The package is at the destination fulfillment center.)
Delivered (The package has been delivered.)
RejectedByBuyer (The package has been rejected by the buyer.)
Undeliverable (The package cannot be delivered.)
ReturningToSeller (The package was not delivered and is being returned to the seller.)
ReturnedToSeller (The package was not delivered and was returned to the seller.)
Lost (The package is lost.)
OutForDelivery (The package is out for delivery.)
Damaged (The package was damaged by the carrier.)

ADD string
ElectronicInvoiceStatuses
array of strings
A list of ElectronicInvoiceStatus values. Used to select orders with electronic invoice statuses that match the specified values.

Possible values:

NotRequired (Electronic invoice submission is not required for this order.)
NotFound (The electronic invoice was not submitted for this order.)
Processing (The electronic invoice is being processed for this order.)
Errored (The last submitted electronic invoice was rejected for this order.)
Accepted (The last submitted electronic invoice was submitted and accepted.)

ADD string
NextToken
string
A string token returned in the response of your previous request.

AmazonOrderIds
array of strings
length ≤ 50
A list of AmazonOrderId values. An AmazonOrderId is an Amazon-defined order identifier, in 3-7-7 format.


ADD string
ActualFulfillmentSupplySourceId
string
The sourceId of the location from where you want the order fulfilled.

IsISPU
boolean
When true, this order is marked to be picked up from a store rather than delivered.


StoreChainStoreId
string
The store chain store identifier. Linked to a specific store in a store chain.

EarliestDeliveryDateBefore
string
Use this date to select orders with an earliest delivery date before (or at) a specified time. The date must be in ISO 8601 format.

EarliestDeliveryDateAfter
string
Use this date to select orders with an earliest delivery date after (or at) a specified time. The date must be in ISO 8601 format.

LatestDeliveryDateBefore
string
Use this date to select orders with a latest delivery date before (or at) a specified time. The date must be in ISO 8601 format.

LatestDeliveryDateAfter
string
Use this date to select orders with a latest delivery date after (or at) a specified time. The date must be in ISO 8601 format.

Responses

200
Success.

Response body
object
payload
object
A list of orders along with additional information to make subsequent API calls.

Orders
array of objects
required
A list of orders.

object
AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

SellerOrderId
string
A seller-defined order identifier.

PurchaseDate
string
required
The date when the order was created.

LastUpdateDate
string
required
The date when the order was last updated.

Note: LastUpdateDate is returned with an incorrect date for orders that were last updated before 2009-04-01.

OrderStatus
string
enum
required
The current order status.

Pending Unshipped PartiallyShipped Shipped Canceled Unfulfillable InvoiceUnconfirmed PendingAvailability

Show Details
Pending	The order has been placed but payment has not been authorized. The order is not ready for shipment. Note that for orders with `OrderType = Standard`, the initial order status is Pending. For orders with `OrderType = Preorder`, the initial order status is `PendingAvailability`, and the order passes into the Pending status when the payment authorization process begins.
Unshipped	Payment has been authorized and order is ready for shipment, but no items in the order have been shipped.
PartiallyShipped	One or more (but not all) items in the order have been shipped.
Shipped	All items in the order have been shipped.
Canceled	The order was canceled.
Unfulfillable	The order cannot be fulfilled. This state applies only to Amazon-fulfilled orders that were not placed on Amazon's retail web site.
InvoiceUnconfirmed	All items in the order have been shipped. The seller has not yet given confirmation to Amazon that the invoice has been shipped to the buyer.
PendingAvailability	This status is available for pre-orders only. The order has been placed, payment has not been authorized, and the release date for the item is in the future. The order is not ready for shipment.
FulfillmentChannel
string
enum
Whether the order was fulfilled by Amazon (AFN) or by the seller (MFN).

MFN AFN

Show Details
MFN	Fulfilled by the seller.
AFN	Fulfilled by Amazon.
SalesChannel
string
The sales channel for the first item in the order.

OrderChannel
string
The order channel for the first item in the order.

ShipServiceLevel
string
The order's shipment service level.

OrderTotal
object
The monetary value of the order.


OrderTotal object
NumberOfItemsShipped
integer
The number of items shipped.

NumberOfItemsUnshipped
integer
The number of items unshipped.

PaymentExecutionDetail
array of objects
A list of payment execution detail items.

object
Payment
object
required
The monetary value of the order.


Payment object
PaymentMethod
string
required
The sub-payment method for an order.

Possible values:

COD: Cash on delivery
GC: Gift card
PointsAccount: Amazon Points
Invoice: Invoice
CreditCard: Credit card
Pix: Pix
Other: Other.
AcquirerId
string
The Brazilian Taxpayer Identifier (CNPJ) of the payment processor or acquiring bank that authorizes the payment.

Note: This attribute is only available for orders in the Brazil (BR) marketplace when the PaymentMethod is CreditCard or Pix.

CardBrand
string
The card network or brand used in the payment transaction (for example, Visa or Mastercard).

Note: This attribute is only available for orders in the Brazil (BR) marketplace when the PaymentMethod is CreditCard.

AuthorizationCode
string
The unique code that confirms the payment authorization.

Note: This attribute is only available for orders in the Brazil (BR) marketplace when the PaymentMethod is CreditCard or Pix.

PaymentMethod
string
enum
The payment method for the order. This property is limited to COD and CVS payment methods. Unless you need the specific COD payment information provided by the PaymentExecutionDetailItem object, we recommend using the PaymentMethodDetails property to get payment method information.

COD CVS Other

Show Details
COD	Cash on delivery.
CVS	Convenience store.
Other	A payment method other than COD and CVS.
PaymentMethodDetails
array of strings
A list of payment method detail items.

MarketplaceId
string
The identifier for the marketplace where the order was placed.

ShipmentServiceLevelCategory
string
The shipment service level category for the order.

Possible values: Expedited, FreeEconomy, NextDay, Priority, SameDay, SecondDay, Scheduled, and Standard.

EasyShipShipmentStatus
string
enum
The status of the Amazon Easy Ship order. This property is only included for Amazon Easy Ship orders.

PendingSchedule PendingPickUp PendingDropOff LabelCanceled PickedUp DroppedOff AtOriginFC AtDestinationFC Delivered RejectedByBuyer Undeliverable ReturningToSeller ReturnedToSeller Lost OutForDelivery Damaged

Show Details
PendingSchedule	The package is awaiting the schedule for pick-up.
PendingPickUp	Amazon has not yet picked up the package from the seller.
PendingDropOff	The seller will deliver the package to the carrier.
LabelCanceled	The seller canceled the pickup.
PickedUp	Amazon has picked up the package from the seller.
DroppedOff	The package was delivered to the carrier by the seller.
AtOriginFC	The package is at the origin fulfillment center.
AtDestinationFC	The package is at the destination fulfillment center.
Delivered	The package has been delivered.
RejectedByBuyer	The package has been rejected by the buyer.
Undeliverable	The package cannot be delivered.
ReturningToSeller	The package was not delivered and is being returned to the seller.
ReturnedToSeller	The package was not delivered and was returned to the seller.
Lost	The package is lost.
OutForDelivery	The package is out for delivery.
Damaged	The package was damaged by the carrier.
CbaDisplayableShippingLabel
string
Custom ship label for Checkout by Amazon (CBA).

OrderType
string
enum
The order's type.

StandardOrder LongLeadTimeOrder Preorder BackOrder SourcingOnDemandOrder

Show Details
StandardOrder	An order that contains items for which the selling partner currently has inventory in stock.
LongLeadTimeOrder	An order that contains items that have a long lead time to ship.
Preorder	An order that contains items with a release date that is in the future.
BackOrder	An order that contains items that already have been released in the market but are currently out of stock and will be available in the future.
SourcingOnDemandOrder	A Sourcing On Demand order.
EarliestShipDate
string
The start of the time period within which you have committed to ship the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders.

Note: EarliestShipDate might not be returned for orders placed before February 1, 2013.

LatestShipDate
string
The end of the time period within which you have committed to ship the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders.

Note: LatestShipDate might not be returned for orders placed before February 1, 2013.

EarliestDeliveryDate
string
The start of the time period within which you have committed to fulfill the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders.

LatestDeliveryDate
string
The end of the time period within which you have committed to fulfill the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders that do not have a PendingAvailability, Pending, or Canceled status.

IsBusinessOrder
boolean
When true, the order is an Amazon Business order. An Amazon Business order is an order where the buyer is a Verified Business Buyer.

IsPrime
boolean
When true, the order is a seller-fulfilled Amazon Prime order.

IsPremiumOrder
boolean
When true, the order has a Premium Shipping Service Level Agreement. For more information about Premium Shipping orders, refer to "Premium Shipping Options" in the Seller Central Help for your marketplace.

IsGlobalExpressEnabled
boolean
When true, the order is a GlobalExpress order.

ReplacedOrderId
string
The order ID value for the order that is being replaced. Returned only if IsReplacementOrder = true.

IsReplacementOrder
boolean
When true, this is a replacement order.

PromiseResponseDueDate
string
Indicates the date by which the seller must respond to the buyer with an estimated ship date. Only returned for Sourcing on Demand orders.

IsEstimatedShipDateSet
boolean
When true, the estimated ship date is set for the order. Only returned for Sourcing on Demand orders.

IsSoldByAB
boolean
When true, the item within this order was bought and re-sold by Amazon Business EU SARL (ABEU). By buying and instantly re-selling your items, ABEU becomes the seller of record, making your inventory available for sale to customers who would not otherwise purchase from a third-party seller.

IsIBA
boolean
When true, the item within this order was bought and re-sold by Amazon Business EU SARL (ABEU). By buying and instantly re-selling your items, ABEU becomes the seller of record, making your inventory available for sale to customers who would not otherwise purchase from a third-party seller.

DefaultShipFromLocationAddress
object
The shipping address for the order.


DefaultShipFromLocationAddress object
BuyerInvoicePreference
string
enum
The buyer's invoicing preference. Sellers can use this data to issue electronic invoices for orders in Turkey.

Note: This attribute is only available in the Turkey marketplace.

INDIVIDUAL BUSINESS

Show Details
INDIVIDUAL	Issues an individual invoice to the buyer.
BUSINESS	Issues a business invoice to the buyer. Tax information is available in `BuyerTaxInformation`.
BuyerTaxInformation
object
Contains the business invoice tax information. Available only in the TR marketplace.


BuyerTaxInformation object
FulfillmentInstruction
object
Contains the instructions about the fulfillment, such as the location from where you want the order filled.


FulfillmentInstruction object
IsISPU
boolean
When true, this order is marked to be picked up from a store rather than delivered.

IsAccessPointOrder
boolean
When true, this order is marked to be delivered to an Access Point. The access location is chosen by the customer. Access Points include Amazon Hub Lockers, Amazon Hub Counters, and pickup points operated by carriers.

MarketplaceTaxInfo
object
Tax information about the marketplace.


MarketplaceTaxInfo object
SellerDisplayName
string
The seller’s friendly name registered in the marketplace where the sale took place. Sellers can use this data to issue electronic invoices for orders in Brazil.

Note: This attribute is only available in the Brazil marketplace for the orders with Pending or Unshipped status.

ShippingAddress
object
The shipping address for the order.


ShippingAddress object
BuyerInfo
object
Buyer information.


BuyerInfo object
AutomatedShippingSettings
object
Contains information regarding the Shipping Settings Automation program, such as whether the order's shipping settings were generated automatically, and what those settings are.


AutomatedShippingSettings object
HasRegulatedItems
boolean
Whether the order contains regulated items which may require additional approval steps before being fulfilled.

ElectronicInvoiceStatus
string
enum
The status of the electronic invoice. Only available for Easy Ship orders and orders in the BR marketplace.

NotRequired NotFound Processing Errored Accepted

Show Details
NotRequired	The order does not require an electronic invoice to be uploaded.
NotFound	The order requires an electronic invoice but it is not uploaded.
Processing	The required electronic invoice was uploaded and is processing.
Errored	The uploaded electronic invoice was not accepted.
Accepted	The uploaded electronic invoice was accepted.
NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

LastUpdatedBefore
string
Use this date to select orders that were last updated before (or at) a specified time. An update is defined as any change in order status, including the creation of a new order. Includes updates made by Amazon and by the seller. Use ISO 8601 format for all dates.

CreatedBefore
string
Use this date to select orders created before (or at) a specified time. Only orders placed before the specified time are returned. The date must be in ISO 8601 format.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.


import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


{
  "payload": {
    "NextToken": "2YgYW55IGNhcm5hbCBwbGVhc3VyZS4",
    "Orders": [
      {
        "AmazonOrderId": "902-3159896-1390916",
        "PurchaseDate": "2017-01-20T19:49:35Z",
        "LastUpdateDate": "2017-01-20T19:49:35Z",
        "OrderStatus": "Pending",
        "FulfillmentChannel": "MFN",
        "NumberOfItemsShipped": 0,
        "NumberOfItemsUnshipped": 0,
        "PaymentMethod": "Other",
        "PaymentMethodDetails": [
          "CreditCard",
          "GiftCertificate"
        ],
        "MarketplaceId": "ATVPDKIKX0DER",
        "ShipmentServiceLevelCategory": "Standard",
        "OrderType": "StandardOrder",
        "EarliestShipDate": "2017-01-20T19:51:16Z",
        "LatestShipDate": "2017-01-25T19:49:35Z",
        "IsBusinessOrder": false,
        "IsPrime": false,
        "IsAccessPointOrder": false,
        "IsGlobalExpressEnabled": false,
        "IsPremiumOrder": false,
        "IsSoldByAB": false,
        "IsIBA": false,
        "ShippingAddress": {
          "Name": "Michigan address",
          "AddressLine1": "1 Cross St.",
          "City": "Canton",
          "StateOrRegion": "MI",
          "PostalCode": "48817",
          "CountryCode": "US"
        },
        "BuyerInfo": {
          "BuyerName": "John Doe",
          "BuyerTaxInfo": {
            "CompanyLegalName": "A Company Name"
          },
          "PurchaseOrderNumber": "1234567890123"
        }
      }
    ]
  }
}


getOrder
get
deprecated
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}

Returns the order that you specify.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Responses

200
Success.

Response body
object
payload
object
Order information.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

SellerOrderId
string
A seller-defined order identifier.

PurchaseDate
string
required
The date when the order was created.

LastUpdateDate
string
required
The date when the order was last updated.

Note: LastUpdateDate is returned with an incorrect date for orders that were last updated before 2009-04-01.

OrderStatus
string
enum
required
The current order status.

Pending Unshipped PartiallyShipped Shipped Canceled Unfulfillable InvoiceUnconfirmed PendingAvailability

Show Details
Pending	The order has been placed but payment has not been authorized. The order is not ready for shipment. Note that for orders with `OrderType = Standard`, the initial order status is Pending. For orders with `OrderType = Preorder`, the initial order status is `PendingAvailability`, and the order passes into the Pending status when the payment authorization process begins.
Unshipped	Payment has been authorized and order is ready for shipment, but no items in the order have been shipped.
PartiallyShipped	One or more (but not all) items in the order have been shipped.
Shipped	All items in the order have been shipped.
Canceled	The order was canceled.
Unfulfillable	The order cannot be fulfilled. This state applies only to Amazon-fulfilled orders that were not placed on Amazon's retail web site.
InvoiceUnconfirmed	All items in the order have been shipped. The seller has not yet given confirmation to Amazon that the invoice has been shipped to the buyer.
PendingAvailability	This status is available for pre-orders only. The order has been placed, payment has not been authorized, and the release date for the item is in the future. The order is not ready for shipment.
FulfillmentChannel
string
enum
Whether the order was fulfilled by Amazon (AFN) or by the seller (MFN).

MFN AFN

Show Details
MFN	Fulfilled by the seller.
AFN	Fulfilled by Amazon.
SalesChannel
string
The sales channel for the first item in the order.

OrderChannel
string
The order channel for the first item in the order.

ShipServiceLevel
string
The order's shipment service level.

OrderTotal
object
The monetary value of the order.


OrderTotal object
NumberOfItemsShipped
integer
The number of items shipped.

NumberOfItemsUnshipped
integer
The number of items unshipped.

PaymentExecutionDetail
array of objects
A list of payment execution detail items.

object
Payment
object
required
The monetary value of the order.


Payment object
PaymentMethod
string
required
The sub-payment method for an order.

Possible values:

COD: Cash on delivery
GC: Gift card
PointsAccount: Amazon Points
Invoice: Invoice
CreditCard: Credit card
Pix: Pix
Other: Other.
AcquirerId
string
The Brazilian Taxpayer Identifier (CNPJ) of the payment processor or acquiring bank that authorizes the payment.

Note: This attribute is only available for orders in the Brazil (BR) marketplace when the PaymentMethod is CreditCard or Pix.

CardBrand
string
The card network or brand used in the payment transaction (for example, Visa or Mastercard).

Note: This attribute is only available for orders in the Brazil (BR) marketplace when the PaymentMethod is CreditCard.

AuthorizationCode
string
The unique code that confirms the payment authorization.

Note: This attribute is only available for orders in the Brazil (BR) marketplace when the PaymentMethod is CreditCard or Pix.

PaymentMethod
string
enum
The payment method for the order. This property is limited to COD and CVS payment methods. Unless you need the specific COD payment information provided by the PaymentExecutionDetailItem object, we recommend using the PaymentMethodDetails property to get payment method information.

COD CVS Other

Show Details
COD	Cash on delivery.
CVS	Convenience store.
Other	A payment method other than COD and CVS.
PaymentMethodDetails
array of strings
A list of payment method detail items.

MarketplaceId
string
The identifier for the marketplace where the order was placed.

ShipmentServiceLevelCategory
string
The shipment service level category for the order.

Possible values: Expedited, FreeEconomy, NextDay, Priority, SameDay, SecondDay, Scheduled, and Standard.

EasyShipShipmentStatus
string
enum
The status of the Amazon Easy Ship order. This property is only included for Amazon Easy Ship orders.

PendingSchedule PendingPickUp PendingDropOff LabelCanceled PickedUp DroppedOff AtOriginFC AtDestinationFC Delivered RejectedByBuyer Undeliverable ReturningToSeller ReturnedToSeller Lost OutForDelivery Damaged

Show Details
PendingSchedule	The package is awaiting the schedule for pick-up.
PendingPickUp	Amazon has not yet picked up the package from the seller.
PendingDropOff	The seller will deliver the package to the carrier.
LabelCanceled	The seller canceled the pickup.
PickedUp	Amazon has picked up the package from the seller.
DroppedOff	The package was delivered to the carrier by the seller.
AtOriginFC	The package is at the origin fulfillment center.
AtDestinationFC	The package is at the destination fulfillment center.
Delivered	The package has been delivered.
RejectedByBuyer	The package has been rejected by the buyer.
Undeliverable	The package cannot be delivered.
ReturningToSeller	The package was not delivered and is being returned to the seller.
ReturnedToSeller	The package was not delivered and was returned to the seller.
Lost	The package is lost.
OutForDelivery	The package is out for delivery.
Damaged	The package was damaged by the carrier.
CbaDisplayableShippingLabel
string
Custom ship label for Checkout by Amazon (CBA).

OrderType
string
enum
The order's type.

StandardOrder LongLeadTimeOrder Preorder BackOrder SourcingOnDemandOrder

Show Details
StandardOrder	An order that contains items for which the selling partner currently has inventory in stock.
LongLeadTimeOrder	An order that contains items that have a long lead time to ship.
Preorder	An order that contains items with a release date that is in the future.
BackOrder	An order that contains items that already have been released in the market but are currently out of stock and will be available in the future.
SourcingOnDemandOrder	A Sourcing On Demand order.
EarliestShipDate
string
The start of the time period within which you have committed to ship the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders.

Note: EarliestShipDate might not be returned for orders placed before February 1, 2013.

LatestShipDate
string
The end of the time period within which you have committed to ship the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders.

Note: LatestShipDate might not be returned for orders placed before February 1, 2013.

EarliestDeliveryDate
string
The start of the time period within which you have committed to fulfill the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders.

LatestDeliveryDate
string
The end of the time period within which you have committed to fulfill the order. In ISO 8601 date time format. Only returned for seller-fulfilled orders that do not have a PendingAvailability, Pending, or Canceled status.

IsBusinessOrder
boolean
When true, the order is an Amazon Business order. An Amazon Business order is an order where the buyer is a Verified Business Buyer.

IsPrime
boolean
When true, the order is a seller-fulfilled Amazon Prime order.

IsPremiumOrder
boolean
When true, the order has a Premium Shipping Service Level Agreement. For more information about Premium Shipping orders, refer to "Premium Shipping Options" in the Seller Central Help for your marketplace.

IsGlobalExpressEnabled
boolean
When true, the order is a GlobalExpress order.

ReplacedOrderId
string
The order ID value for the order that is being replaced. Returned only if IsReplacementOrder = true.

IsReplacementOrder
boolean
When true, this is a replacement order.

PromiseResponseDueDate
string
Indicates the date by which the seller must respond to the buyer with an estimated ship date. Only returned for Sourcing on Demand orders.

IsEstimatedShipDateSet
boolean
When true, the estimated ship date is set for the order. Only returned for Sourcing on Demand orders.

IsSoldByAB
boolean
When true, the item within this order was bought and re-sold by Amazon Business EU SARL (ABEU). By buying and instantly re-selling your items, ABEU becomes the seller of record, making your inventory available for sale to customers who would not otherwise purchase from a third-party seller.

IsIBA
boolean
When true, the item within this order was bought and re-sold by Amazon Business EU SARL (ABEU). By buying and instantly re-selling your items, ABEU becomes the seller of record, making your inventory available for sale to customers who would not otherwise purchase from a third-party seller.

DefaultShipFromLocationAddress
object
The shipping address for the order.


DefaultShipFromLocationAddress object
BuyerInvoicePreference
string
enum
The buyer's invoicing preference. Sellers can use this data to issue electronic invoices for orders in Turkey.

Note: This attribute is only available in the Turkey marketplace.

INDIVIDUAL BUSINESS

Show Details
INDIVIDUAL	Issues an individual invoice to the buyer.
BUSINESS	Issues a business invoice to the buyer. Tax information is available in `BuyerTaxInformation`.
BuyerTaxInformation
object
Contains the business invoice tax information. Available only in the TR marketplace.


BuyerTaxInformation object
FulfillmentInstruction
object
Contains the instructions about the fulfillment, such as the location from where you want the order filled.


FulfillmentInstruction object
IsISPU
boolean
When true, this order is marked to be picked up from a store rather than delivered.

IsAccessPointOrder
boolean
When true, this order is marked to be delivered to an Access Point. The access location is chosen by the customer. Access Points include Amazon Hub Lockers, Amazon Hub Counters, and pickup points operated by carriers.

MarketplaceTaxInfo
object
Tax information about the marketplace.


MarketplaceTaxInfo object
SellerDisplayName
string
The seller’s friendly name registered in the marketplace where the sale took place. Sellers can use this data to issue electronic invoices for orders in Brazil.

Note: This attribute is only available in the Brazil marketplace for the orders with Pending or Unshipped status.

ShippingAddress
object
The shipping address for the order.


ShippingAddress object
BuyerInfo
object
Buyer information.


BuyerInfo object
AutomatedShippingSettings
object
Contains information regarding the Shipping Settings Automation program, such as whether the order's shipping settings were generated automatically, and what those settings are.


AutomatedShippingSettings object
HasRegulatedItems
boolean
Whether the order contains regulated items which may require additional approval steps before being fulfilled.

ElectronicInvoiceStatus
string
enum
The status of the electronic invoice. Only available for Easy Ship orders and orders in the BR marketplace.

NotRequired NotFound Processing Errored Accepted

Show Details
NotRequired	The order does not require an electronic invoice to be uploaded.
NotFound	The order requires an electronic invoice but it is not uploaded.
Processing	The required electronic invoice was uploaded and is processing.
Errored	The uploaded electronic invoice was not accepted.
Accepted	The uploaded electronic invoice was accepted.
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "payload": {
    "AmazonOrderId": "902-3159896-1390916",
    "PurchaseDate": "2017-01-20T19:49:35Z",
    "LastUpdateDate": "2017-01-20T19:49:35Z",
    "OrderStatus": "Pending",
    "FulfillmentChannel": "MFN",
    "NumberOfItemsShipped": 0,
    "NumberOfItemsUnshipped": 0,
    "PaymentMethod": "Other",
    "PaymentMethodDetails": [
      "CreditCard",
      "GiftCertificate"
    ],
    "MarketplaceId": "ATVPDKIKX0DER",
    "ShipmentServiceLevelCategory": "Standard",
    "OrderType": "StandardOrder",
    "EarliestShipDate": "2017-01-20T19:51:16Z",
    "LatestShipDate": "2017-01-25T19:49:35Z",
    "IsBusinessOrder": false,
    "IsPrime": false,
    "IsGlobalExpressEnabled": false,
    "IsPremiumOrder": false,
    "IsSoldByAB": false,
    "IsIBA": false,
    "DefaultShipFromLocationAddress": {
      "Name": "MFNIntegrationTestMerchant",
      "AddressLine1": "2201 WESTLAKE AVE",
      "City": "SEATTLE",
      "StateOrRegion": "WA",
      "PostalCode": "98121-2778",
      "CountryCode": "US",
      "Phone": "+1 480-386-0930 ext. 73824",
      "AddressType": "Commercial"
    },
    "FulfillmentInstruction": {
      "FulfillmentSupplySourceId": "sampleSupplySourceId"
    },
    "IsISPU": false,
    "IsAccessPointOrder": false,
    "ShippingAddress": {
      "Name": "Michigan address",
      "AddressLine1": "1 Cross St.",
      "City": "Canton",
      "StateOrRegion": "MI",
      "PostalCode": "48817",
      "CountryCode": "US"
    },
    "BuyerInfo": {
      "BuyerName": "John Doe",
      "BuyerTaxInfo": {
        "CompanyLegalName": "A Company Name"
      },
      "PurchaseOrderNumber": "1234567890123"
    },
    "AutomatedShippingSettings": {
      "HasAutomatedShippingSettings": false
    }
  }
}

getOrderBuyerInfo
get
deprecated
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/buyerInfo


Returns buyer information for the order that you specify.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
The Amazon order identifier in 3-7-7 format.

Responses

200
Success.

Response body
object
payload
object
Buyer information for an order.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

BuyerName
string
The buyer name or the recipient name.

BuyerCounty
string
The county of the buyer.

Note: This attribute is only available in the Brazil marketplace.

BuyerTaxInfo
object
Tax information about the buyer.


BuyerTaxInfo object
PurchaseOrderNumber
string
The purchase order (PO) number entered by the buyer at checkout. Only returned for orders where the buyer entered a PO number at checkout.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/buyerInfo"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


{
  "payload": {
    "AmazonOrderId": "902-3159896-1390916",
    "BuyerName": "John Smith",
    "BuyerTaxInfo": {
      "CompanyLegalName": "Company Name"
    },
    "PurchaseOrderNumber": "1234567890123"
  }
}

getOrderAddress
get
deprecated
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/address

Returns the shipping address for the order that you specify.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
The Amazon order identifier in 3-7-7 format.

Responses

200
Success.

Response body
object
payload
object
The shipping address for the order.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

BuyerCompanyName
string
The company name of the contact buyer. For IBA orders, the buyer company must be Amazon entities.

ShippingAddress
object
The shipping address for the order.


ShippingAddress object
DeliveryPreferences
object
Contains all of the delivery instructions provided by the customer for the shipping address.


DeliveryPreferences object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/address"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "payload": {
    "AmazonOrderId": "902-3159896-1390916",
    "ShippingAddress": {
      "Name": "Michigan address",
      "AddressLine1": "1 cross st",
      "City": "Canton",
      "StateOrRegion": "MI",
      "PostalCode": "48817",
      "CountryCode": "US"
    }
  }
}

getOrderItems
get
deprecated
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/orderItems

Returns detailed order item information for the order that you specify. If NextToken is provided, it's used to retrieve the next page of order items.

Note: When an order is in the Pending state (the order has been placed but payment has not been authorized), the getOrderItems operation does not return information about pricing, taxes, shipping charges, gift status or promotions for the order items in the order. After an order leaves the Pending state (this occurs when payment has been authorized) and enters the Unshipped, Partially Shipped, or Shipped state, the getOrderItems operation returns information about pricing, taxes, shipping charges, gift status and promotions for the order items in the order.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Query Params
NextToken
string
A string token returned in the response of your previous request.

Responses

200
Success.

Response body
object
payload
object
The order items list along with the order ID.

OrderItems
array of objects
required
A list of order items.

object
ASIN
string
required
The item's Amazon Standard Identification Number (ASIN).

SellerSKU
string
The item's seller stock keeping unit (SKU).

OrderItemId
string
required
An Amazon-defined order item identifier.

AssociatedItems
array of objects
A list of associated items that a customer has purchased with a product. For example, a tire installation service purchased with tires.

object
OrderId
string
The order item's order identifier, in 3-7-7 format.

OrderItemId
string
An Amazon-defined item identifier for the associated item.

AssociationType
string
enum
The type of association an item has with an order item.

VALUE_ADD_SERVICE

Show Details
VALUE_ADD_SERVICE	The associated item is a service order.
Title
string
The item's name.

QuantityOrdered
integer
required
The number of items in the order.

QuantityShipped
integer
The number of items shipped.

ProductInfo
object
Product information on the number of items.


ProductInfo object
PointsGranted
object
The number of Amazon Points offered with the purchase of an item, and their monetary value.


PointsGranted object
ItemPrice
object
The monetary value of the order.


ItemPrice object
ShippingPrice
object
The monetary value of the order.


ShippingPrice object
ItemTax
object
The monetary value of the order.


ItemTax object
ShippingTax
object
The monetary value of the order.


ShippingTax object
ShippingDiscount
object
The monetary value of the order.


ShippingDiscount object
ShippingDiscountTax
object
The monetary value of the order.


ShippingDiscountTax object
PromotionDiscount
object
The monetary value of the order.


PromotionDiscount object
PromotionDiscountTax
object
The monetary value of the order.


PromotionDiscountTax object
PromotionIds
array of strings
A list of promotion identifiers provided by the seller when the promotions were created.

CODFee
object
The monetary value of the order.


CODFee object
CODFeeDiscount
object
The monetary value of the order.


CODFeeDiscount object
IsGift
string
Indicates whether the item is a gift.

Possible values: true and false.

ConditionNote
string
The condition of the item, as described by the seller.

ConditionId
string
The condition of the item.

Possible values: New, Used, Collectible, Refurbished, Preorder, and Club.

ConditionSubtypeId
string
The subcondition of the item.

Possible values: New, Mint, Very Good, Good, Acceptable, Poor, Club, OEM, Warranty, Refurbished Warranty, Refurbished, Open Box, Any, and Other.

ScheduledDeliveryStartDate
string
The start date of the scheduled delivery window in the time zone for the order destination. In ISO 8601 date time format.

ScheduledDeliveryEndDate
string
The end date of the scheduled delivery window in the time zone for the order destination. In ISO 8601 date time format.

PriceDesignation
string
Indicates that the selling price is a special price that is only available for Amazon Business orders. For more information about the Amazon Business Seller Program, refer to the Amazon Business website.

Possible values: BusinessPrice

TaxCollection
object
Information about withheld taxes.


TaxCollection object
SerialNumberRequired
boolean
When true, the product type for this item has a serial number.

Only returned for Amazon Easy Ship orders.

IsTransparency
boolean
When true, the ASIN is enrolled in Transparency. The Transparency serial number that you must submit is determined by:

1D or 2D Barcode: This has a T logo. Submit either the 29-character alpha-numeric identifier beginning with AZ or ZA, or the 38-character Serialized Global Trade Item Number (SGTIN).
2D Barcode SN: Submit the 7- to 20-character serial number barcode, which likely has the prefix SN. The serial number is applied to the same side of the packaging as the GTIN (UPC/EAN/ISBN) barcode.
QR code SN: Submit the URL that the QR code generates.

IossNumber
string
The IOSS number of the marketplace. Sellers shipping to the EU from outside the EU must provide this IOSS number to their carrier when Amazon has collected the VAT on the sale.

StoreChainStoreId
string
The store chain store identifier. Linked to a specific store in a store chain.

DeemedResellerCategory
string
enum
The category of deemed reseller. This applies to selling partners that are not based in the EU and is used to help them meet the VAT Deemed Reseller tax laws in the EU and UK.

IOSS UOSS

Show Details
IOSS	Import one stop shop. The item being purchased is not held in the EU for shipment.
UOSS	Union one stop shop. The item being purchased is held in the EU for shipment.
BuyerInfo
object
A single item's buyer information.


BuyerInfo object
BuyerRequestedCancel
object
Information about whether or not a buyer requested cancellation.


BuyerRequestedCancel object
SerialNumbers
array of strings
A list of serial numbers for electronic products that are shipped to customers. Returned for FBA orders only.

SubstitutionPreferences
object
Substitution preferences for an order item.


SubstitutionPreferences object
Measurement
object
Measurement information for an order item.


Measurement object
ShippingConstraints
object
Delivery constraints applicable to this order.


ShippingConstraints object
AmazonPrograms
object
Contains the list of programs that Amazon associates with an item.

Possible programs are:

Subscribe and Save: Offers recurring, scheduled deliveries to Amazon customers and Amazon Business customers for their frequently ordered products. - FBM Ship+: Unlocks expedited shipping without the extra cost. Helps you to provide accurate and fast delivery dates to Amazon customers. You also receive protection from late deliveries, a discount on expedited shipping rates, and cash back when you ship.

AmazonPrograms object
NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.


import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/orderItems"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


{
  "payload": {
    "AmazonOrderId": "903-1671087-0812628",
    "NextToken": "2YgYW55IGNhcm5hbCBwbGVhc3VyZS4",
    "OrderItems": [
      {
        "ASIN": "BT0093TELA",
        "OrderItemId": "68828574383266",
        "SellerSKU": "CBA_OTF_1",
        "Title": "Example item name",
        "QuantityOrdered": 1,
        "QuantityShipped": 1,
        "PointsGranted": {
          "PointsNumber": 10,
          "PointsMonetaryValue": {
            "CurrencyCode": "JPY",
            "Amount": "10.00"
          }
        },
        "ItemPrice": {
          "CurrencyCode": "JPY",
          "Amount": "25.99"
        },
        "ShippingPrice": {
          "CurrencyCode": "JPY",
          "Amount": "1.26"
        },
        "ScheduledDeliveryEndDate": "2013-09-09T01:30:00Z",
        "ScheduledDeliveryStartDate": "2013-09-07T02:00:00Z",
        "CODFee": {
          "CurrencyCode": "JPY",
          "Amount": "10.00"
        },
        "CODFeeDiscount": {
          "CurrencyCode": "JPY",
          "Amount": "1.00"
        },
        "PriceDesignation": "BusinessPrice",
        "BuyerInfo": {
          "BuyerCustomizedInfo": {
            "CustomizedURL": "https://zme-caps.amazon.com/t/bR6qHkzSOxuB/J8nbWhze0Bd3DkajkOdY-XQbWkFralegp2sr_QZiKEE/1"
          },
          "GiftMessageText": "For you!",
          "GiftWrapPrice": {
            "CurrencyCode": "GBP",
            "Amount": "41.99"
          },
          "GiftWrapLevel": "Classic"
        },
        "BuyerRequestedCancel": {
          "IsBuyerRequestedCancel": "true",
          "BuyerCancelReason": "Found cheaper somewhere else."
        },
        "SerialNumbers": [
          "854"
        ]
      },
      {
        "ASIN": "BCTU1104UEFB",
        "OrderItemId": "79039765272157",
        "SellerSKU": "CBA_OTF_5",
        "Title": "Example item name",
        "QuantityOrdered": 2,
        "ItemPrice": {
          "CurrencyCode": "JPY",
          "Amount": "17.95"
        },
        "PromotionIds": [
          "FREESHIP"
        ],
        "ConditionId": "Used",
        "ConditionSubtypeId": "Mint",
        "ConditionNote": "Example ConditionNote",
        "PriceDesignation": "BusinessPrice",
        "BuyerInfo": {
          "BuyerCustomizedInfo": {
            "CustomizedURL": "https://zme-caps.amazon.com/t/bR6qHkzSOxuB/J8nbWhze0Bd3DkajkOdY-XQbWkFralegp2sr_QZiKEE/1"
          },
          "GiftMessageText": "For you!",
          "GiftWrapPrice": {
            "CurrencyCode": "JPY",
            "Amount": "1.99"
          },
          "GiftWrapLevel": "Classic"
        },
        "BuyerRequestedCancel": {
          "IsBuyerRequestedCancel": "true",
          "BuyerCancelReason": "Found cheaper somewhere else."
        }
      }
    ]
  }
}

getOrderItemsBuyerInfo
get
deprecated
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/orderItems/buyerInfo

Returns buyer information for the order items in the order that you specify.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Query Params
NextToken
string
A string token returned in the response of your previous request.

Responses

200
Success.

Response body
object
payload
object
A single order item's buyer information list with the order ID.

OrderItems
array of objects
required
A single order item's buyer information list.

object
OrderItemId
string
required
An Amazon-defined order item identifier.

BuyerCustomizedInfo
object
Buyer information for custom orders from the Amazon Custom program.


BuyerCustomizedInfo object
GiftWrapPrice
object
The monetary value of the order.


GiftWrapPrice object
GiftWrapTax
object
The monetary value of the order.


GiftWrapTax object
GiftMessageText
string
A gift message provided by the buyer.

Note: This attribute is only available for MFN (fulfilled by seller) orders.

GiftWrapLevel
string
The gift wrap level specified by the buyer.

NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.


import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/orderItems/buyerInfo"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "payload": {
    "OrderItemId": "903-1671087-0812628",
    "BuyerCustomizedInfo": {
      "CustomizedURL": "https://zme-caps.amazon.com/t/bR6qHkzSOxuB/J8nbWhze0Bd3DkajkOdY-XQbWkFralegp2sr_QZiKEE/1"
    },
    "GiftMessageText": "For you!",
    "GiftWrapPrice": {
      "CurrencyCode": "JPY",
      "Amount": "1.99"
    },
    "GiftWrapLevel": "Classic"
  }
}

updateShipmentStatus
post
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/shipment

Update the shipment status for an order that you specify.

Usage Plan:

Rate (requests per second)	Burst
5	15
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Body Params

Expand All
⬍
The request body for the updateShipmentStatus operation.

marketplaceId
string
required
The unobfuscated marketplace identifier.

shipmentStatus
string
enum
required
The shipment status to apply.

Show Details
ReadyForPickup	Ready for pickup.
PickedUp	Picked up.
RefusedPickup	Refused pickup.

ReadyForPickup
Allowed:

ReadyForPickup

PickedUp

RefusedPickup
orderItems
array of objects
For partial shipment status updates, the list of order items and quantities to be updated.


ADD object
Responses

204
Success.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/shipment"

payload = { "shipmentStatus": "ReadyForPickup" }
headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)


getOrderRegulatedInfo
get
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/regulatedInfo

Returns regulated information for the order that you specify.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
The Amazon order identifier in 3-7-7 format.

Headers
accept
string
enum
Defaults to application/json
Generated from available response content types


application/json
Allowed:

ApprovedOrder

PendingOrder

RejectedOrder

application/json
Responses

200
Success.

Response body

application/json
object
payload
object
The order's regulated information along with its verification status.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

RegulatedInformation
object
required
The regulated information collected during purchase and used to verify the order.


RegulatedInformation object
RequiresDosageLabel
boolean
required
When true, the order requires attaching a dosage information label when shipped.

RegulatedOrderVerificationStatus
object
required
The verification status of the order, along with associated approval or rejection metadata.


RegulatedOrderVerificationStatus object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/regulatedInfo"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "payload": {
    "AmazonOrderId": "string",
    "RegulatedInformation": {
      "Fields": [
        {
          "FieldId": "string",
          "FieldLabel": "string",
          "FieldType": "Text",
          "FieldValue": "string"
        }
      ]
    },
    "RequiresDosageLabel": true,
    "RegulatedOrderVerificationStatus": {
      "Status": "Pending",
      "RequiresMerchantAction": true,
      "ValidRejectionReasons": [
        {
          "RejectionReasonId": "string",
          "RejectionReasonDescription": "string"
        }
      ],
      "RejectionReason": {
        "RejectionReasonId": "string",
        "RejectionReasonDescription": "string"
      },
      "ReviewDate": "string",
      "ExternalReviewerId": "string",
      "ValidVerificationDetails": [
        {
          "VerificationDetailType": "string",
          "ValidVerificationStatuses": [
            "Pending"
          ]
        }
      ]
    }
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

updateVerificationStatus
patch
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/regulatedInfo

Updates (approves or rejects) the verification status of an order containing regulated products.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
The Amazon order identifier in 3-7-7 format.

Body Params

Expand All
⬍
The request body for the updateVerificationStatus operation.

regulatedOrderVerificationStatus
object
required
The updated values of the VerificationStatus field.


regulatedOrderVerificationStatus object
Responses

204
Success.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/regulatedInfo"

headers = {
    "accept": "*/*",
    "content-type": "application/json"
}

response = requests.patch(url, headers=headers)

print(response.text)

confirmShipment
post
https://sellingpartnerapi-na.amazon.com/orders/v0/orders/{orderId}/shipmentConfirmation

Updates the shipment confirmation status for a specified order.

Usage Plan:

Rate (requests per second)	Burst
2	10
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Body Params

Expand All
⬍
Request body of confirmShipment.

packageDetail
object
required
Properties of packages


packageDetail object
codCollectionMethod
string
enum
The COD collection method (only supported in the JP marketplace).


Allowed:

DirectPayment
marketplaceId
string
required
The unobfuscated marketplace identifier.

Responses

204
Success.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/v0/orders/orderId/shipmentConfirmation"

headers = {
    "accept": "*/*",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

searchOrders
get
https://sellingpartnerapi-na.amazon.com/orders/2026-01-01/orders

Returns orders that are created or updated during the time period that you specify. You can filter the response for specific types of orders.

Query Params
createdAfter
date-time
The response includes orders created at or after this time. The date must be in ISO 8601 format.

Note: You must provide exactly one of createdAfter and lastUpdatedAfter in your request. If createdAfter is provided, neither lastUpdatedAfter nor lastUpdatedBefore may be provided.

createdBefore
date-time
The response includes orders created at or before this time. The date must be in ISO 8601 format.

Note: If you include createdAfter in the request, createdBefore is optional, and if provided must be equal to or after the createdAfter date and at least two minutes before the time of the request. If createdBefore is provided, neither lastUpdatedAfter nor lastUpdatedBefore may be provided.

lastUpdatedAfter
date-time
The response includes orders updated at or after this time. An update is defined as any change made by Amazon or by the seller, including an update to the order status. The date must be in ISO 8601 format.

Note: You must provide exactly one of createdAfter and lastUpdatedAfter. If lastUpdatedAfter is provided, neither createdAfter nor createdBefore may be provided.

lastUpdatedBefore
date-time
The response includes orders updated at or before this time. An update is defined as any change made by Amazon or by the seller, including an update to the order status. The date must be in ISO 8601 format.

Note: If you include lastUpdatedAfter in the request, lastUpdatedBefore is optional, and if provided must be equal to or after the lastUpdatedAfter date and at least two minutes before the time of the request. If lastUpdatedBefore is provided, neither createdAfter nor createdBefore may be provided.

fulfillmentStatuses
array of strings
A list of FulfillmentStatus values you can use to filter the results.

Show Details
PENDING_AVAILABILITY	This status is available for pre-orders only. The order has been placed, payment has not been authorized, and the release date of the item is in the future. The order is not ready for shipment.
PENDING	The order has been placed but is not ready for shipment. For standard orders, the initial order status is `PENDING`. For pre-orders, the initial order status is `PENDING_AVAILABILITY`, and the order passes into the `PENDING` status when payment authorization begins.
UNSHIPPED	The order is ready for shipment, but no items in the order have been shipped.
PARTIALLY_SHIPPED	At least one, but not all, items in the order have been shipped.
SHIPPED	All items have been shipped to the customer.
CANCELLED	The order has been canceled and will not be fulfilled.
UNFULFILLABLE	The order cannot be fulfilled. This state only applies to Amazon-fulfilled orders that were not placed on Amazon's retail web site.

ADD string
marketplaceIds
array of strings
length ≤ 50
The response includes orders that were placed in marketplaces you include in this list.

Refer to Marketplace IDs for a complete list of marketplaceId values.


ADD string
fulfilledBy
array of strings
The response includes orders that are fulfilled by the parties that you include in this list.

Show Details
MERCHANT	Fulfilled by the merchant
AMAZON	Fulfilled by Amazon

ADD string
maxResultsPerPage
integer
The maximum number of orders that can be returned per page. The value must be between 1 and 100. Default: 100.

paginationToken
string
Pagination occurs when a request produces a response that exceeds the maxResultsPerPage. This means that the response is divided into individual pages. To retrieve the next page, you must pass the nextToken value as the paginationToken query parameter in the next request. You will not receive a nextToken value on the last page.

includedData
array of strings
A list of datasets to include in the response.

Show Details
BUYER	Information about the buyer who purchased the order.
RECIPIENT	Information about the recipient to whom the order is delivered.
PROCEEDS	The revenue and financial breakdown for the order and order items.
EXPENSE	The cost information about the order and order items.
PROMOTION	The discount and promotional offer details applied to the order and order items.
CANCELLATION	Cancellation information applied to the order and order items.
FULFILLMENT	Information about how the order and order items are processed and shipped.
PACKAGES	Information about shipping packages and tracking.

ADD string
Responses

200
Success.

Response body
object
orders
array of objects
required
An array containing all orders that match the search criteria.

object
orderId
string
required
An Amazon-defined order identifier.

orderAliases
array of objects
Alternative identifiers that can be used to reference this order, such as seller-defined order numbers.

object
aliasId
string
required
The alternative identifier value that can be used to reference this order.

aliasType
string
required
The kind of alternative identifier this represents.

Possible values: SELLER_ORDER_ID

createdTime
date-time
required
The time when the customer placed the order. In ISO 8601 format.

lastUpdatedTime
date-time
required
The most recent time when any aspect of this order was modified by Amazon or the seller. In ISO 8601 format.

programs
array of strings
Special programs associated with this order that may affect fulfillment or customer experience.

Possible values: AMAZON_BAZAAR, AMAZON_BUSINESS, AMAZON_EASY_SHIP, AMAZON_HAUL, DELIVERY_BY_AMAZON, FBM_SHIP_PLUS, IN_STORE_PICK_UP, PREMIUM, PREORDER, PRIME

associatedOrders
array of objects
Other orders that have a direct relationship to this order, such as replacement or exchange orders.

object
orderId
string
The unique identifier of the related order that is associated with the current order.

associationType
string
The relationship between the current order and the associated order.

Possible values: REPLACEMENT_ORIGINAL_ID, EXCHANGE_ORIGINAL_ID

salesChannel
object
required
Information about where the customer placed this order.


salesChannel object
buyer
object
Information about the customer who purchased the order.


buyer object
recipient
object
Information about the recipient to whom the order should be delivered.


recipient object
proceeds
object
The money that the seller receives from the sale of the order.


proceeds object
fulfillment
object
Information about how the order is being processed, packed, and shipped to the customer.


fulfillment object
orderItems
array of objects
required
The list of all order items included in this order.

object
orderItemId
string
required
A unique identifier for this specific item within the order.

quantityOrdered
integer
required
The number of units of this item that the customer ordered.

measurement
object
Specifies the unit of measure and quantity for items that are sold by weight, volume, length, or other measurements rather than simple count.


measurement object
programs
array of strings
Special programs that apply specifically to this item within the order.

Possible values: TRANSPARENCY, SUBSCRIBE_AND_SAVE

product
object
required
Product information for an order item.


product object
proceeds
object
The money that the seller receives from the sale of this specific item.


proceeds object
expense
object
The expense information related to this specific item.


expense object
promotion
object
Details about any discounts, coupons, or promotional offers applied to this item.


promotion object
cancellation
object
The cancellation information of the order item.


cancellation object
fulfillment
object
Information about how the order item should be processed, packed, and shipped to the customer.


fulfillment object
packages
array of objects
Shipping packages created for this order, including tracking information. Note: Only available for merchant-fulfilled (FBM) orders.

object
packageReferenceId
string
required
A unique identifier for this package within the context of the order.

createdTime
date-time
The exact time when this shipping package was created and prepared for shipment. In ISO 8601 format.

packageStatus
object
Current status and detailed tracking information for a shipping package throughout the delivery process.


packageStatus object
carrier
string
The carrier responsible for transporting this package to the customer.

shipTime
date-time
The exact time when this package was handed over to the carrier and began its journey to the customer. In ISO 8601 format.

shippingService
string
The specific shipping method or service used for delivering this package.

trackingNumber
string
The carrier-provided tracking number that customers can use to monitor the package's delivery progress.

shipFromAddress
object
The physical address of the merchant.


shipFromAddress object
packageItems
array of objects
A list of all order items included in this specific package.

object
orderItemId
string
required
Unique identifier of the order item included in this package.

quantity
integer
required
Number of units of this item included in the package shipment.

transparencyCodes
array of strings
The transparency codes associated with this item for product authentication.

pagination
object
When a request has results that are not included in the response, pagination occurs. This means the results are divided into individual pages. To retrieve a different page, you must pass the token value as the paginationToken query parameter in the subsequent request. All other parameters must be provided with the same values that were provided with the request that generated this token, with the exception of maxResultsPerPage and includedData, which can be modified between calls. The token will expire after 24 hours. When there are no other pages to fetch, the pagination field will be absent from the response.

nextToken
string
A token that can be used to fetch the next page of results.

lastUpdatedBefore
date-time
Only orders updated before the specified time are returned. The date must be in ISO 8601 format.

createdBefore
date-time
Only orders placed before the specified time are returned. The date must be in ISO 8601 format.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/2026-01-01/orders"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "orders": [
    {
      "orderId": "123-4567890-1234567",
      "orderAliases": [
        {
          "aliasId": "SELLER-ORDER-2024-001",
          "aliasType": "SELLER_ORDER_ID"
        }
      ],
      "createdTime": "2024-12-25T10:30:00Z",
      "lastUpdatedTime": "2024-12-25T14:45:00Z",
      "programs": [
        "PRIME",
        "AMAZON_BUSINESS"
      ],
      "associatedOrders": [
        {
          "orderId": "123-4567890-1234566",
          "associationType": "REPLACEMENT_ORIGINAL_ID"
        }
      ],
      "salesChannel": {
        "channelName": "AMAZON",
        "marketplaceId": "ATVPDKIKX0DER",
        "marketplaceName": "Amazon.com"
      },
      "buyer": {
        "buyerName": "John Smith",
        "buyerEmail": "buyer-email@marketplace.amazon.com",
        "buyerCompanyName": "Smith Industries LLC",
        "buyerPurchaseOrderNumber": "PO-2024-12345"
      },
      "recipient": {
        "deliveryAddress": {
          "name": "John Smith",
          "companyName": "Smith Industries LLC",
          "addressLine1": "123 Main Street",
          "addressLine2": "Suite 456",
          "addressLine3": "",
          "city": "Seattle",
          "districtOrCounty": "King County",
          "stateOrRegion": "WA",
          "municipality": "",
          "postalCode": "98101",
          "countryCode": "US",
          "phone": "555-123-4567",
          "addressType": "COMMERCIAL"
        },
        "deliveryPreference": {
          "dropOffLocation": "Front desk reception",
          "addressInstruction": "Enter through main lobby, ask for John Smith at reception",
          "deliveryTime": {
            "businessHours": [
              {
                "dayOfWeek": "MON",
                "timeWindows": [
                  {
                    "startTime": {
                      "hour": 9,
                      "minute": 0
                    },
                    "endTime": {
                      "hour": 17,
                      "minute": 0
                    }
                  }
                ]
              },
              {
                "dayOfWeek": "TUE",
                "timeWindows": [
                  {
                    "startTime": {
                      "hour": 9,
                      "minute": 0
                    },
                    "endTime": {
                      "hour": 17,
                      "minute": 0
                    }
                  }
                ]
              },
              {
                "dayOfWeek": "WED",
                "timeWindows": [
                  {
                    "startTime": {
                      "hour": 9,
                      "minute": 0
                    },
                    "endTime": {
                      "hour": 17,
                      "minute": 0
                    }
                  }
                ]
              },
              {
                "dayOfWeek": "THU",
                "timeWindows": [
                  {
                    "startTime": {
                      "hour": 9,
                      "minute": 0
                    },
                    "endTime": {
                      "hour": 17,
                      "minute": 0
                    }
                  }
                ]
              },
              {
                "dayOfWeek": "FRI",
                "timeWindows": [
                  {
                    "startTime": {
                      "hour": 9,
                      "minute": 0
                    },
                    "endTime": {
                      "hour": 17,
                      "minute": 0
                    }
                  }
                ]
              }
            ],
            "exceptionDates": [
              {
                "exceptionDate": "2024-12-31",
                "exceptionDateType": "CLOSED",
                "timeWindows": []
              }
            ]
          },
          "deliveryCapabilities": [
            "HAS_ACCESS_POINT",
            "PALLET_ENABLED"
          ]
        }
      },
      "proceeds": {
        "grandTotal": {
          "amount": "149.99",
          "currencyCode": "USD"
        }
      },
      "fulfillment": {
        "fulfillmentStatus": "SHIPPED",
        "fulfilledBy": "MERCHANT",
        "fulfillmentServiceLevel": "STANDARD",
        "shipByWindow": {
          "earliestDateTime": "2024-12-26T00:00:00Z",
          "latestDateTime": "2024-12-27T23:59:59Z"
        },
        "deliverByWindow": {
          "earliestDateTime": "2024-12-28T00:00:00Z",
          "latestDateTime": "2024-12-30T23:59:59Z"
        }
      },
      "orderItems": [
        {
          "orderItemId": "12345678901234",
          "quantityOrdered": 2,
          "programs": [
            "TRANSPARENCY",
            "SUBSCRIBE_AND_SAVE"
          ],
          "product": {
            "asin": "B08N5WRWNW",
            "title": "Echo Dot (4th Gen) | Smart speaker with Alexa | Charcoal",
            "sellerSku": "ECHO-DOT-4-CHARCOAL",
            "condition": {
              "conditionType": "NEW",
              "conditionSubtype": "NEW",
              "conditionNote": "Brand new in original packaging"
            },
            "price": {
              "unitPrice": {
                "amount": "49.99",
                "currencyCode": "USD"
              },
              "priceDesignation": "BUSINESS_PRICE"
            },
            "customization": {
              "customizedUrl": "https://amazon.com/custom/view/12345"
            }
          },
          "proceeds": {
            "proceedsTotal": {
              "amount": "99.98",
              "currencyCode": "USD"
            },
            "breakdowns": [
              {
                "type": "ITEM",
                "subtotal": {
                  "amount": "99.98",
                  "currencyCode": "USD"
                }
              },
              {
                "type": "TAX",
                "subtotal": {
                  "amount": "0.02",
                  "currencyCode": "USD"
                },
                "detailedBreakdowns": [
                  {
                    "subtype": "ITEM",
                    "value": {
                      "amount": "0.02",
                      "currencyCode": "USD"
                    }
                  }
                ]
              }
            ]
          },
          "promotion": {
            "breakdowns": [
              {
                "promotionId": "PROMO-HOLIDAY-2024"
              }
            ]
          },
          "cancellation": {
            "cancellationRequest": {
              "requester": "BUYER",
              "cancelReason": "Changed mind about purchase"
            }
          },
          "fulfillment": {
            "quantityFulfilled": 2,
            "quantityUnfulfilled": 0,
            "packing": {
              "giftOption": {
                "giftMessage": "Happy Holidays! Enjoy your new smart speakers.",
                "giftWrapLevel": "PREMIUM"
              }
            },
            "shipping": {
              "scheduledDeliveryWindow": {
                "earliestDateTime": "2024-12-28T09:00:00Z",
                "latestDateTime": "2024-12-28T17:00:00Z"
              },
              "shippingConstraints": {
                "palletDelivery": "MANDATORY",
                "cashOnDelivery": "MANDATORY",
                "signatureConfirmation": "MANDATORY",
                "recipientIdentityVerification": "MANDATORY",
                "recipientAgeVerification": "MANDATORY"
              }
            }
          }
        },
        {
          "orderItemId": "12345678901235",
          "quantityOrdered": 1,
          "programs": [],
          "product": {
            "asin": "B07XJ8C8F5",
            "title": "Fire TV Stick 4K with Alexa Voice Remote",
            "sellerSku": "FIRE-TV-4K-2021",
            "condition": {
              "conditionType": "NEW",
              "conditionSubtype": "NEW",
              "conditionNote": ""
            },
            "price": {
              "unitPrice": {
                "amount": "49.99",
                "currencyCode": "USD"
              }
            }
          },
          "proceeds": {
            "proceedsTotal": {
              "amount": "49.99",
              "currencyCode": "USD"
            },
            "breakdowns": [
              {
                "type": "ITEM",
                "subtotal": {
                  "amount": "49.99",
                  "currencyCode": "USD"
                }
              }
            ]
          },
          "fulfillment": {
            "quantityFulfilled": 1,
            "quantityUnfulfilled": 0,
            "shipping": {
              "scheduledDeliveryWindow": {
                "earliestDateTime": "2024-12-28T09:00:00Z",
                "latestDateTime": "2024-12-28T17:00:00Z"
              },
              "shippingConstraints": {
                "signatureConfirmation": "MANDATORY"
              }
            }
          }
        }
      ],
      "packages": [
        {
          "packageReferenceId": "PKG-2024-001",
          "createdTime": "2024-12-25T15:00:00Z",
          "packageStatus": {
            "status": "DELIVERED",
            "detailedStatus": "DELIVERED"
          },
          "carrier": "UPS",
          "shipTime": "2024-12-25T14:00:00Z",
          "shippingService": "UPS Ground",
          "trackingNumber": "1Z999AA1234567890",
          "shipFromAddress": {
            "name": "Smith Electronics Warehouse",
            "addressLine1": "456 Industrial Blvd",
            "addressLine2": "Building A",
            "city": "Bellevue",
            "districtOrCounty": "King County",
            "stateOrRegion": "WA",
            "postalCode": "98004",
            "countryCode": "US"
          },
          "packageItems": [
            {
              "orderItemId": "12345678901234",
              "quantity": 2,
              "transparencyCodes": [
                "T12345ABCDE67890",
                "T12346ABCDF67891"
              ]
            },
            {
              "orderItemId": "12345678901235",
              "quantity": 1,
              "transparencyCodes": [
                "T67890GHIJK12345"
              ]
            }
          ]
        }
      ]
    }
  ],
  "pagination": {
    "nextToken": "2YgYW55IGNhcm5hbCBwbGVhc3VyZS4"
  },
  "lastUpdatedBefore": "2024-12-25T15:00:00Z"
}

getOrder
get
https://sellingpartnerapi-na.amazon.com/orders/2026-01-01/orders/{orderId}

Returns the order that you specify.

Path Params
orderId
string
required
An Amazon-defined order identifier.

Query Params
includedData
array of strings
A list of datasets to include in the response.

Show Details
BUYER	Information about the buyer who purchased the order.
RECIPIENT	Information about the recipient to whom the order is delivered.
PROCEEDS	The revenue and financial breakdown for the order and order items.
EXPENSE	The cost information applied to the order and order items.
PROMOTION	The discount and promotional offer details applied to the order and order items.
CANCELLATION	Cancellation information applied to the order and order items.
FULFILLMENT	Information about how this order and order items are processed and shipped.
PACKAGES	Shipping packages and tracking information.

ADD string
Responses

200
Success.

Response body
object
order
object
required
Comprehensive information about a customer order.

orderId
string
required
An Amazon-defined order identifier.

orderAliases
array of objects
Alternative identifiers that can be used to reference this order, such as seller-defined order numbers.

object
aliasId
string
required
The alternative identifier value that can be used to reference this order.

aliasType
string
required
The kind of alternative identifier this represents.

Possible values: SELLER_ORDER_ID

createdTime
date-time
required
The time when the customer placed the order. In ISO 8601 format.

lastUpdatedTime
date-time
required
The most recent time when any aspect of this order was modified by Amazon or the seller. In ISO 8601 format.

programs
array of strings
Special programs associated with this order that may affect fulfillment or customer experience.

Possible values: AMAZON_BAZAAR, AMAZON_BUSINESS, AMAZON_EASY_SHIP, AMAZON_HAUL, DELIVERY_BY_AMAZON, FBM_SHIP_PLUS, IN_STORE_PICK_UP, PREMIUM, PREORDER, PRIME

associatedOrders
array of objects
Other orders that have a direct relationship to this order, such as replacement or exchange orders.

object
orderId
string
The unique identifier of the related order that is associated with the current order.

associationType
string
The relationship between the current order and the associated order.

Possible values: REPLACEMENT_ORIGINAL_ID, EXCHANGE_ORIGINAL_ID

salesChannel
object
required
Information about where the customer placed this order.


salesChannel object
buyer
object
Information about the customer who purchased the order.


buyer object
recipient
object
Information about the recipient to whom the order should be delivered.


recipient object
proceeds
object
The money that the seller receives from the sale of the order.


proceeds object
fulfillment
object
Information about how the order is being processed, packed, and shipped to the customer.


fulfillment object
orderItems
array of objects
required
The list of all order items included in this order.

object
orderItemId
string
required
A unique identifier for this specific item within the order.

quantityOrdered
integer
required
The number of units of this item that the customer ordered.

measurement
object
Specifies the unit of measure and quantity for items that are sold by weight, volume, length, or other measurements rather than simple count.


measurement object
programs
array of strings
Special programs that apply specifically to this item within the order.

Possible values: TRANSPARENCY, SUBSCRIBE_AND_SAVE

product
object
required
Product information for an order item.


product object
proceeds
object
The money that the seller receives from the sale of this specific item.


proceeds object
expense
object
The expense information related to this specific item.


expense object
promotion
object
Details about any discounts, coupons, or promotional offers applied to this item.


promotion object
cancellation
object
The cancellation information of the order item.


cancellation object
fulfillment
object
Information about how the order item should be processed, packed, and shipped to the customer.


fulfillment object
packages
array of objects
Shipping packages created for this order, including tracking information. Note: Only available for merchant-fulfilled (FBM) orders.

object
packageReferenceId
string
required
A unique identifier for this package within the context of the order.

createdTime
date-time
The exact time when this shipping package was created and prepared for shipment. In ISO 8601 format.

packageStatus
object
Current status and detailed tracking information for a shipping package throughout the delivery process.


packageStatus object
carrier
string
The carrier responsible for transporting this package to the customer.

shipTime
date-time
The exact time when this package was handed over to the carrier and began its journey to the customer. In ISO 8601 format.

shippingService
string
The specific shipping method or service used for delivering this package.

trackingNumber
string
The carrier-provided tracking number that customers can use to monitor the package's delivery progress.

shipFromAddress
object
The physical address of the merchant.


shipFromAddress object
packageItems
array of objects
A list of all order items included in this specific package.

object
orderItemId
string
required
Unique identifier of the order item included in this package.

quantity
integer
required
Number of units of this item included in the package shipment.

transparencyCodes
array of strings
The transparency codes associated with this item for product authentication.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/orders/2026-01-01/orders/orderId"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "order": {
    "orderId": "202-1234567-8901234",
    "orderAliases": [
      {
        "aliasId": "UK-MERCHANT-ORDER-2024-001",
        "aliasType": "SELLER_ORDER_ID"
      }
    ],
    "createdTime": "2024-12-25T09:15:00Z",
    "lastUpdatedTime": "2024-12-25T16:30:00Z",
    "programs": [
      "PRIME"
    ],
    "salesChannel": {
      "channelName": "AMAZON",
      "marketplaceId": "A1F83G8C2ARO7P",
      "marketplaceName": "Amazon.co.uk"
    },
    "buyer": {
      "buyerName": "James Wilson",
      "buyerEmail": "buyer-email@marketplace.amazon.co.uk"
    },
    "recipient": {
      "deliveryAddress": {
        "name": "James Wilson",
        "companyName": "Wilson Electronics Ltd",
        "addressLine1": "123 High Street",
        "addressLine2": "Unit 4B",
        "addressLine3": "",
        "city": "Manchester",
        "districtOrCounty": "Greater Manchester",
        "stateOrRegion": "England",
        "municipality": "",
        "postalCode": "M1 2AB",
        "countryCode": "GB",
        "phone": "+44 161 123 4567",
        "addressType": "COMMERCIAL"
      }
    },
    "proceeds": {
      "grandTotal": {
        "amount": "103.97",
        "currencyCode": "GBP"
      }
    },
    "fulfillment": {
      "fulfillmentStatus": "SHIPPED",
      "fulfilledBy": "MERCHANT",
      "fulfillmentServiceLevel": "STANDARD",
      "shipByWindow": {
        "earliestDateTime": "2024-12-25T00:00:00Z",
        "latestDateTime": "2024-12-26T23:59:59Z"
      },
      "deliverByWindow": {
        "earliestDateTime": "2024-12-27T00:00:00Z",
        "latestDateTime": "2024-12-30T23:59:59Z"
      }
    },
    "orderItems": [
      {
        "orderItemId": "20212345678901",
        "quantityOrdered": 3,
        "programs": [
          "TRANSPARENCY"
        ],
        "product": {
          "asin": "B08DFPV54V",
          "title": "Echo Dot (4th Gen) | Smart speaker with Alexa | Charcoal",
          "sellerSku": "ECHO-DOT-4-UK-CHARCOAL-3PACK",
          "condition": {
            "conditionType": "NEW",
            "conditionSubtype": "NEW",
            "conditionNote": "Brand new, sealed in original packaging"
          },
          "price": {
            "unitPrice": {
              "amount": "29.99",
              "currencyCode": "GBP"
            },
            "priceDesignation": "BUSINESS_PRICE"
          },
          "serialNumbers": [
            "ED4UK-2024-ABC123456789",
            "ED4UK-2024-DEF987654321",
            "ED4UK-2024-GHI456789123"
          ],
          "customization": {
            "customizedUrl": ""
          }
        },
        "proceeds": {
          "proceedsTotal": {
            "amount": "103.97",
            "currencyCode": "GBP"
          },
          "breakdowns": [
            {
              "type": "ITEM",
              "subtotal": {
                "amount": "89.97",
                "currencyCode": "GBP"
              }
            },
            {
              "type": "SHIPPING",
              "subtotal": {
                "amount": "10.00",
                "currencyCode": "GBP"
              }
            },
            {
              "type": "TAX",
              "subtotal": {
                "amount": "4.00",
                "currencyCode": "GBP"
              },
              "detailedBreakdowns": [
                {
                  "subtype": "ITEM",
                  "value": {
                    "amount": "3.00",
                    "currencyCode": "GBP"
                  }
                },
                {
                  "subtype": "SHIPPING",
                  "value": {
                    "amount": "1.00",
                    "currencyCode": "GBP"
                  }
                }
              ]
            }
          ]
        },
        "promotion": {
          "breakdowns": [
            {
              "promotionId": "UK-BOXING-DAY-2024"
            }
          ]
        },
        "fulfillment": {
          "quantityFulfilled": 3,
          "quantityUnfulfilled": 0,
          "packing": {
            "giftOption": {
              "giftMessage": "Happy Christmas! Hope you enjoy your new smart speakers.",
              "giftWrapLevel": "PREMIUM"
            }
          },
          "shipping": {
            "scheduledDeliveryWindow": {
              "earliestDateTime": "2024-12-27T09:00:00Z",
              "latestDateTime": "2024-12-27T17:00:00Z"
            },
            "shippingConstraints": {
              "signatureConfirmation": "MANDATORY",
              "recipientIdentityVerification": "MANDATORY"
            },
            "internationalShipping": {
              "iossNumber": "IM1234567890"
            }
          }
        }
      }
    ],
    "packages": [
      {
        "packageReferenceId": "UK-PKG-2024-001",
        "createdTime": "2024-12-25T16:45:00Z",
        "packageStatus": {
          "status": "IN_TRANSIT",
          "detailedStatus": "OUT_FOR_DELIVERY"
        },
        "carrier": "Royal Mail",
        "shipTime": "2024-12-26T14:00:00Z",
        "shippingService": "Royal Mail Tracked 48",
        "trackingNumber": "RR123456789GB",
        "shipFromAddress": {
          "name": "TechGear UK Warehouse",
          "addressLine1": "Industrial Estate Unit 15",
          "addressLine2": "Riverside Business Park",
          "addressLine3": "",
          "city": "Birmingham",
          "districtOrCounty": "West Midlands",
          "stateOrRegion": "England",
          "municipality": "",
          "postalCode": "B12 0XY",
          "countryCode": "GB"
        },
        "packageItems": [
          {
            "orderItemId": "20212345678901",
            "quantity": 3,
            "transparencyCodes": [
              "T12345ABCDE67890UK",
              "T12346ABCDF67891UK",
              "T12347ABCDG67892UK"
            ]
          }
        ]
      }
    ]
  }
}



getEligibleShipmentServices
post
https://sellingpartnerapi-na.amazon.com/mfn/v0/eligibleShippingServices

Returns a list of shipping service offers that satisfy the specified shipment request details.

Usage Plan:

Rate (requests per second)	Burst
6	12
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that are applied to the requested operation when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the SP-API.

Body Params

Expand All
⬍
The request schema for the GetEligibleShipmentServices operation.

ShipmentRequestDetails
object
required
Shipment information required for requesting shipping service offers or for creating a shipment.


ShipmentRequestDetails object
ShippingOfferingFilter
object
Filter for use when requesting eligible shipping services.


ShippingOfferingFilter object
Responses

200
Success.

Response body
object
payload
object
The payload for the getEligibleShipmentServices operation.

ShippingServiceList
array of objects
required
A list of shipping services offers.

object
ShippingServiceName
string
required
A plain text representation of a carrier's shipping service. For example, "UPS Ground" or "FedEx Standard Overnight".

CarrierName
string
required
The name of the carrier.

ShippingServiceId
string
required
An Amazon-defined shipping service identifier.

ShippingServiceOfferId
string
required
An Amazon-defined shipping service offer identifier.

ShipDate
date-time
required
Date-time formatted timestamp.

EarliestEstimatedDeliveryDate
date-time
Date-time formatted timestamp.

LatestEstimatedDeliveryDate
date-time
Date-time formatted timestamp.

Rate
object
required
Currency type and amount.


Rate object
RateWithAdjustments
object
required
Currency type and amount.


RateWithAdjustments object
AdjustmentItemList
array of objects
List of adjustments.

object
RateItemID
string
enum
required
Unique identifier for the RateItem.

FBM_SHIP_PLUS_CREDIT

Show Details
FBM_SHIP_PLUS_CREDIT	Charge adjustment for FBM Ship+.
RateItemType
string
enum
Type for the RateItem.

INCLUDED

Show Details
INCLUDED	RateItem is included but not guaranteed to offer for the shipping service.
RateItemCharge
object
Currency type and amount.


RateItemCharge object
RateItemNameLocalization
string
Localized name for the RateItem.

ShippingServiceOptions
object
required
Extra services provided by a carrier.


ShippingServiceOptions object
AvailableShippingServiceOptions
object
The available shipping service options.


AvailableShippingServiceOptions object
AvailableLabelFormats
array of objects
List of label formats.

AvailableFormatOptionsForLabel
array of objects
The available label formats.

object
IncludePackingSlipWithLabel
boolean
When true, include a packing slip with the label.

LabelFormat
string
enum
The label format.

PDF PNG ZPL203 ZPL300 ShippingServiceDefault

Show Details
PDF	Portable Document Format (pdf).
PNG	Portable Network Graphics (png) format.
ZPL203	Zebra Programming Language (zpl) format, 203 dots per inch resolution.
ZPL300	Zebra Programming Language (zpl) format, 300 dots per inch resolution.
ShippingServiceDefault	The default provided by the shipping service.
RequiresAdditionalSellerInputs
boolean
required
When true, additional seller inputs are required.

Benefits
object
Benefits that are included and excluded for each shipping offer. Benefits represents services provided by Amazon (for example, CLAIMS_PROTECTED) when sellers purchase shipping through Amazon. Benefit details are made available for any shipment placed on or after January 1st 2024 00:00 UTC.


Benefits object
RejectedShippingServiceList
array of objects
List of services that are for some reason unavailable for this request

object
CarrierName
string
required
The rejected shipping carrier name. For example, USPS.

ShippingServiceName
string
required
The rejected shipping service localized name. For example, FedEx Standard Overnight.

ShippingServiceId
string
required
An Amazon-defined shipping service identifier.

RejectionReasonCode
string
required
A reason code meant to be consumed programatically. For example, CARRIER_CANNOT_SHIP_TO_POBOX.

RejectionReasonMessage
string
A localized human readable description of the rejected reason.

TemporarilyUnavailableCarrierList
array of objects
A list of temporarily unavailable carriers.

object
CarrierName
string
required
The name of the carrier.

TermsAndConditionsNotAcceptedCarrierList
array of objects
List of carriers whose terms and conditions were not accepted by the seller.

object
CarrierName
string
required
The name of the carrier.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/mfn/v0/eligibleShippingServices"

payload = { "ShipmentRequestDetails": {
        "Weight": { "Unit": "oz" },
        "ShippingServiceOptions": {
            "DeliveryExperience": "DeliveryConfirmationWithAdultSignature",
            "CarrierWillPickUp": True
        }
    } }
headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)

{
  "payload": {
    "ShippingServiceList": [
      {
        "ShippingServiceName": "string",
        "CarrierName": "string",
        "ShippingServiceId": "string",
        "ShippingServiceOfferId": "string",
        "ShipDate": "2026-04-21T13:47:20.138Z",
        "EarliestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
        "LatestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
        "Rate": {
          "CurrencyCode": "string",
          "Amount": 0
        },
        "RateWithAdjustments": {
          "CurrencyCode": "string",
          "Amount": 0
        },
        "AdjustmentItemList": [
          {
            "RateItemID": "FBM_SHIP_PLUS_CREDIT",
            "RateItemType": "INCLUDED",
            "RateItemCharge": {
              "CurrencyCode": "string",
              "Amount": 0
            },
            "RateItemNameLocalization": "string"
          }
        ],
        "ShippingServiceOptions": {
          "DeliveryExperience": "DeliveryConfirmationWithAdultSignature",
          "DeclaredValue": {
            "CurrencyCode": "string",
            "Amount": 0
          },
          "CarrierWillPickUp": true,
          "CarrierWillPickUpOption": "CarrierWillPickUp",
          "LabelFormat": "PDF"
        },
        "AvailableShippingServiceOptions": {
          "AvailableCarrierWillPickUpOptions": [
            {
              "CarrierWillPickUpOption": "CarrierWillPickUp",
              "Charge": {
                "CurrencyCode": "string",
                "Amount": 0
              }
            }
          ],
          "AvailableDeliveryExperienceOptions": [
            {
              "DeliveryExperienceOption": "DeliveryConfirmationWithAdultSignature",
              "Charge": {
                "CurrencyCode": "string",
                "Amount": 0
              }
            }
          ]
        },
        "AvailableLabelFormats": [
          "PDF"
        ],
        "AvailableFormatOptionsForLabel": [
          {
            "IncludePackingSlipWithLabel": true,
            "LabelFormat": "PDF"
          }
        ],
        "RequiresAdditionalSellerInputs": true,
        "Benefits": {
          "IncludedBenefits": [
            "string"
          ],
          "ExcludedBenefits": [
            {
              "Benefit": "string",
              "ReasonCodes": [
                "string"
              ]
            }
          ]
        }
      }
    ],
    "RejectedShippingServiceList": [
      {
        "CarrierName": "string",
        "ShippingServiceName": "string",
        "ShippingServiceId": "string",
        "RejectionReasonCode": "string",
        "RejectionReasonMessage": "string"
      }
    ],
    "TemporarilyUnavailableCarrierList": [
      {
        "CarrierName": "string"
      }
    ],
    "TermsAndConditionsNotAcceptedCarrierList": [
      {
        "CarrierName": "string"
      }
    ]
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

getShipment
get
https://sellingpartnerapi-na.amazon.com/mfn/v0/shipments/{shipmentId}

Returns the shipment information for an existing shipment.

Usage Plan:

Rate (requests per second)	Burst
1	1
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that are applied to the requested operation when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the SP-API.

Path Params
shipmentId
string
required
The Amazon-defined shipment identifier for the shipment.

Responses

200
Success.

Response body
object
payload
object
The details of a shipment. Includes the shipment status.

ShipmentId
string
required
An Amazon-defined shipment identifier.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

SellerOrderId
string
length ≤ 64
A seller-defined order identifier.

ItemList
array of objects
required
The list of items you want to include in a shipment.

object
OrderItemId
string
required
An Amazon-defined identifier for an individual item in an order.

Quantity
int32
required
The number of items.

ItemWeight
object
The weight.


ItemWeight object
ItemDescription
string
The description of the item.

TransparencyCodeList
array of objects
A list of transparency codes.

ItemLevelSellerInputsList
array of objects
A list of additional seller input pairs required to purchase shipping.

object
AdditionalInputFieldName
string
required
The name of the additional input field.

AdditionalSellerInput
object
required
Additional information required to purchase shipping.


AdditionalSellerInput object
LiquidVolume
object
Liquid volume.


LiquidVolume object
IsHazmat
boolean
When true, the item qualifies as hazardous materials (hazmat). Defaults to false.

DangerousGoodsDetails
object
Details related to any dangerous goods or items that are shipped.


DangerousGoodsDetails object
ShipFromAddress
object
required
The postal address information.


ShipFromAddress object
ShipToAddress
object
required
The postal address information.


ShipToAddress object
PackageDimensions
object
required
The dimensions of a package contained in a shipment.


PackageDimensions object
Weight
object
required
The weight.


Weight object
Insurance
object
required
Currency type and amount.


Insurance object
ShippingService
object
required
A shipping service offer made by a carrier.


ShippingService object
Label
object
required
Data for creating a shipping label and dimensions for printing the label.


Label object
Status
string
enum
required
The shipment status.

Purchased RefundPending RefundRejected RefundApplied

Show Details
Purchased	The seller purchased a label by calling the `createShipment` operation.
RefundPending	The seller requested a label refund by calling the `cancelShipment` operation, and the refund request is being processed by the carrier. Note: A seller can create a new shipment for an order while `Status = RefundPending` for a canceled shipment. After you request a label refund (by calling `cancelShipment`), the status of the order remains `Shipped`.
RefundRejected	The label refund request is rejected by the carrier. A refund request is rejected because the cancellation window has expired or the carrier has already accepted the shipment for delivery. Cancellation policies vary by carrier. For more information about carrier cancellation policies, refer to the Seller Central Help for your marketplace.
RefundApplied	The refund has been approved and credited to the seller's account.
TrackingId
string
The shipment tracking identifier provided by the carrier.

CreatedDate
date-time
required
Date-time formatted timestamp.

LastUpdatedDate
date-time
Date-time formatted timestamp.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/mfn/v0/shipments/shipmentId"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "payload": {
    "ShipmentId": "string",
    "AmazonOrderId": "string",
    "SellerOrderId": "string",
    "ItemList": [
      {
        "OrderItemId": "string",
        "Quantity": 0,
        "ItemWeight": {
          "Value": 0,
          "Unit": "oz"
        },
        "ItemDescription": "string",
        "TransparencyCodeList": [
          "string"
        ],
        "ItemLevelSellerInputsList": [
          {
            "AdditionalInputFieldName": "string",
            "AdditionalSellerInput": {
              "DataType": "string",
              "ValueAsString": "string",
              "ValueAsBoolean": true,
              "ValueAsInteger": 0,
              "ValueAsTimestamp": "2026-04-21T13:47:20.138Z",
              "ValueAsAddress": {
                "Name": "string",
                "AddressLine1": "string",
                "AddressLine2": "string",
                "AddressLine3": "string",
                "DistrictOrCounty": "string",
                "Email": "string",
                "City": "string",
                "StateOrProvinceCode": "string",
                "PostalCode": "string",
                "CountryCode": "string",
                "Phone": "string"
              },
              "ValueAsWeight": {
                "Value": 0,
                "Unit": "oz"
              },
              "ValueAsDimension": {
                "value": 0,
                "unit": "inches"
              },
              "ValueAsCurrency": {
                "CurrencyCode": "string",
                "Amount": 0
              }
            }
          }
        ],
        "LiquidVolume": {
          "Unit": "ML",
          "Value": 0
        },
        "IsHazmat": true,
        "DangerousGoodsDetails": {
          "UnitedNationsRegulatoryId": "string",
          "TransportationRegulatoryClass": "string",
          "PackingGroup": "I",
          "PackingInstruction": "PI965_SECTION_IA"
        }
      }
    ],
    "ShipFromAddress": {
      "Name": "string",
      "AddressLine1": "string",
      "AddressLine2": "string",
      "AddressLine3": "string",
      "DistrictOrCounty": "string",
      "Email": "string",
      "City": "string",
      "StateOrProvinceCode": "string",
      "PostalCode": "string",
      "CountryCode": "string",
      "Phone": "string"
    },
    "ShipToAddress": {
      "Name": "string",
      "AddressLine1": "string",
      "AddressLine2": "string",
      "AddressLine3": "string",
      "DistrictOrCounty": "string",
      "Email": "string",
      "City": "string",
      "StateOrProvinceCode": "string",
      "PostalCode": "string",
      "CountryCode": "string",
      "Phone": "string"
    },
    "PackageDimensions": {
      "Length": 0,
      "Width": 0,
      "Height": 0,
      "Unit": "inches",
      "PredefinedPackageDimensions": "FedEx_Box_10kg"
    },
    "Weight": {
      "Value": 0,
      "Unit": "oz"
    },
    "Insurance": {
      "CurrencyCode": "string",
      "Amount": 0
    },
    "ShippingService": {
      "ShippingServiceName": "string",
      "CarrierName": "string",
      "ShippingServiceId": "string",
      "ShippingServiceOfferId": "string",
      "ShipDate": "2026-04-21T13:47:20.138Z",
      "EarliestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
      "LatestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
      "Rate": {
        "CurrencyCode": "string",
        "Amount": 0
      },
      "RateWithAdjustments": {
        "CurrencyCode": "string",
        "Amount": 0
      },
      "AdjustmentItemList": [
        {
          "RateItemID": "FBM_SHIP_PLUS_CREDIT",
          "RateItemType": "INCLUDED",
          "RateItemCharge": {
            "CurrencyCode": "string",
            "Amount": 0
          },
          "RateItemNameLocalization": "string"
        }
      ],
      "ShippingServiceOptions": {
        "DeliveryExperience": "DeliveryConfirmationWithAdultSignature",
        "DeclaredValue": {
          "CurrencyCode": "string",
          "Amount": 0
        },
        "CarrierWillPickUp": true,
        "CarrierWillPickUpOption": "CarrierWillPickUp",
        "LabelFormat": "PDF"
      },
      "AvailableShippingServiceOptions": {
        "AvailableCarrierWillPickUpOptions": [
          {
            "CarrierWillPickUpOption": "CarrierWillPickUp",
            "Charge": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          }
        ],
        "AvailableDeliveryExperienceOptions": [
          {
            "DeliveryExperienceOption": "DeliveryConfirmationWithAdultSignature",
            "Charge": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          }
        ]
      },
      "AvailableLabelFormats": [
        "PDF"
      ],
      "AvailableFormatOptionsForLabel": [
        {
          "IncludePackingSlipWithLabel": true,
          "LabelFormat": "PDF"
        }
      ],
      "RequiresAdditionalSellerInputs": true,
      "Benefits": {
        "IncludedBenefits": [
          "string"
        ],
        "ExcludedBenefits": [
          {
            "Benefit": "string",
            "ReasonCodes": [
              "string"
            ]
          }
        ]
      }
    },
    "Label": {
      "CustomTextForLabel": "string",
      "Dimensions": {
        "Length": 0,
        "Width": 0,
        "Unit": "inches"
      },
      "FileContents": {
        "Contents": "string",
        "FileType": "application/pdf",
        "Checksum": "string"
      },
      "LabelFormat": "PDF",
      "StandardIdForLabel": "AmazonOrderId"
    },
    "Status": "Purchased",
    "TrackingId": "string",
    "CreatedDate": "2026-04-21T13:47:20.138Z",
    "LastUpdatedDate": "2026-04-21T13:47:20.138Z"
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}


    cancelShipment
delete
https://sellingpartnerapi-na.amazon.com/mfn/v0/shipments/{shipmentId}

Cancel the shipment indicated by the specified shipment identifier.

Usage Plan:

Rate (requests per second)	Burst
1	1
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that are applied to the requested operation when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the SP-API.

Path Params
shipmentId
string
required
The Amazon-defined shipment identifier for the shipment to cancel.

Responses

200
Success.

Response body
object
payload
object
The details of a shipment. Includes the shipment status.

ShipmentId
string
required
An Amazon-defined shipment identifier.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

SellerOrderId
string
length ≤ 64
A seller-defined order identifier.

ItemList
array of objects
required
The list of items you want to include in a shipment.

object
OrderItemId
string
required
An Amazon-defined identifier for an individual item in an order.

Quantity
int32
required
The number of items.

ItemWeight
object
The weight.


ItemWeight object
ItemDescription
string
The description of the item.

TransparencyCodeList
array of objects
A list of transparency codes.

ItemLevelSellerInputsList
array of objects
A list of additional seller input pairs required to purchase shipping.

object
AdditionalInputFieldName
string
required
The name of the additional input field.

AdditionalSellerInput
object
required
Additional information required to purchase shipping.


AdditionalSellerInput object
LiquidVolume
object
Liquid volume.


LiquidVolume object
IsHazmat
boolean
When true, the item qualifies as hazardous materials (hazmat). Defaults to false.

DangerousGoodsDetails
object
Details related to any dangerous goods or items that are shipped.


DangerousGoodsDetails object
ShipFromAddress
object
required
The postal address information.


ShipFromAddress object
ShipToAddress
object
required
The postal address information.


ShipToAddress object
PackageDimensions
object
required
The dimensions of a package contained in a shipment.


PackageDimensions object
Weight
object
required
The weight.


Weight object
Insurance
object
required
Currency type and amount.


Insurance object
ShippingService
object
required
A shipping service offer made by a carrier.


ShippingService object
Label
object
required
Data for creating a shipping label and dimensions for printing the label.


Label object
Status
string
enum
required
The shipment status.

Purchased RefundPending RefundRejected RefundApplied

Show Details
Purchased	The seller purchased a label by calling the `createShipment` operation.
RefundPending	The seller requested a label refund by calling the `cancelShipment` operation, and the refund request is being processed by the carrier. Note: A seller can create a new shipment for an order while `Status = RefundPending` for a canceled shipment. After you request a label refund (by calling `cancelShipment`), the status of the order remains `Shipped`.
RefundRejected	The label refund request is rejected by the carrier. A refund request is rejected because the cancellation window has expired or the carrier has already accepted the shipment for delivery. Cancellation policies vary by carrier. For more information about carrier cancellation policies, refer to the Seller Central Help for your marketplace.
RefundApplied	The refund has been approved and credited to the seller's account.
TrackingId
string
The shipment tracking identifier provided by the carrier.

CreatedDate
date-time
required
Date-time formatted timestamp.

LastUpdatedDate
date-time
Date-time formatted timestamp.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/mfn/v0/shipments/shipmentId"

headers = {"accept": "application/json"}

response = requests.delete(url, headers=headers)

print(response.text)

{
  "payload": {
    "ShipmentId": "string",
    "AmazonOrderId": "string",
    "SellerOrderId": "string",
    "ItemList": [
      {
        "OrderItemId": "string",
        "Quantity": 0,
        "ItemWeight": {
          "Value": 0,
          "Unit": "oz"
        },
        "ItemDescription": "string",
        "TransparencyCodeList": [
          "string"
        ],
        "ItemLevelSellerInputsList": [
          {
            "AdditionalInputFieldName": "string",
            "AdditionalSellerInput": {
              "DataType": "string",
              "ValueAsString": "string",
              "ValueAsBoolean": true,
              "ValueAsInteger": 0,
              "ValueAsTimestamp": "2026-04-21T13:47:20.138Z",
              "ValueAsAddress": {
                "Name": "string",
                "AddressLine1": "string",
                "AddressLine2": "string",
                "AddressLine3": "string",
                "DistrictOrCounty": "string",
                "Email": "string",
                "City": "string",
                "StateOrProvinceCode": "string",
                "PostalCode": "string",
                "CountryCode": "string",
                "Phone": "string"
              },
              "ValueAsWeight": {
                "Value": 0,
                "Unit": "oz"
              },
              "ValueAsDimension": {
                "value": 0,
                "unit": "inches"
              },
              "ValueAsCurrency": {
                "CurrencyCode": "string",
                "Amount": 0
              }
            }
          }
        ],
        "LiquidVolume": {
          "Unit": "ML",
          "Value": 0
        },
        "IsHazmat": true,
        "DangerousGoodsDetails": {
          "UnitedNationsRegulatoryId": "string",
          "TransportationRegulatoryClass": "string",
          "PackingGroup": "I",
          "PackingInstruction": "PI965_SECTION_IA"
        }
      }
    ],
    "ShipFromAddress": {
      "Name": "string",
      "AddressLine1": "string",
      "AddressLine2": "string",
      "AddressLine3": "string",
      "DistrictOrCounty": "string",
      "Email": "string",
      "City": "string",
      "StateOrProvinceCode": "string",
      "PostalCode": "string",
      "CountryCode": "string",
      "Phone": "string"
    },
    "ShipToAddress": {
      "Name": "string",
      "AddressLine1": "string",
      "AddressLine2": "string",
      "AddressLine3": "string",
      "DistrictOrCounty": "string",
      "Email": "string",
      "City": "string",
      "StateOrProvinceCode": "string",
      "PostalCode": "string",
      "CountryCode": "string",
      "Phone": "string"
    },
    "PackageDimensions": {
      "Length": 0,
      "Width": 0,
      "Height": 0,
      "Unit": "inches",
      "PredefinedPackageDimensions": "FedEx_Box_10kg"
    },
    "Weight": {
      "Value": 0,
      "Unit": "oz"
    },
    "Insurance": {
      "CurrencyCode": "string",
      "Amount": 0
    },
    "ShippingService": {
      "ShippingServiceName": "string",
      "CarrierName": "string",
      "ShippingServiceId": "string",
      "ShippingServiceOfferId": "string",
      "ShipDate": "2026-04-21T13:47:20.138Z",
      "EarliestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
      "LatestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
      "Rate": {
        "CurrencyCode": "string",
        "Amount": 0
      },
      "RateWithAdjustments": {
        "CurrencyCode": "string",
        "Amount": 0
      },
      "AdjustmentItemList": [
        {
          "RateItemID": "FBM_SHIP_PLUS_CREDIT",
          "RateItemType": "INCLUDED",
          "RateItemCharge": {
            "CurrencyCode": "string",
            "Amount": 0
          },
          "RateItemNameLocalization": "string"
        }
      ],
      "ShippingServiceOptions": {
        "DeliveryExperience": "DeliveryConfirmationWithAdultSignature",
        "DeclaredValue": {
          "CurrencyCode": "string",
          "Amount": 0
        },
        "CarrierWillPickUp": true,
        "CarrierWillPickUpOption": "CarrierWillPickUp",
        "LabelFormat": "PDF"
      },
      "AvailableShippingServiceOptions": {
        "AvailableCarrierWillPickUpOptions": [
          {
            "CarrierWillPickUpOption": "CarrierWillPickUp",
            "Charge": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          }
        ],
        "AvailableDeliveryExperienceOptions": [
          {
            "DeliveryExperienceOption": "DeliveryConfirmationWithAdultSignature",
            "Charge": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          }
        ]
      },
      "AvailableLabelFormats": [
        "PDF"
      ],
      "AvailableFormatOptionsForLabel": [
        {
          "IncludePackingSlipWithLabel": true,
          "LabelFormat": "PDF"
        }
      ],
      "RequiresAdditionalSellerInputs": true,
      "Benefits": {
        "IncludedBenefits": [
          "string"
        ],
        "ExcludedBenefits": [
          {
            "Benefit": "string",
            "ReasonCodes": [
              "string"
            ]
          }
        ]
      }
    },
    "Label": {
      "CustomTextForLabel": "string",
      "Dimensions": {
        "Length": 0,
        "Width": 0,
        "Unit": "inches"
      },
      "FileContents": {
        "Contents": "string",
        "FileType": "application/pdf",
        "Checksum": "string"
      },
      "LabelFormat": "PDF",
      "StandardIdForLabel": "AmazonOrderId"
    },
    "Status": "Purchased",
    "TrackingId": "string",
    "CreatedDate": "2026-04-21T13:47:20.138Z",
    "LastUpdatedDate": "2026-04-21T13:47:20.138Z"
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

createShipment
post
https://sellingpartnerapi-na.amazon.com/mfn/v0/shipments

Create a shipment with the information provided.

Usage Plan:

Rate (requests per second)	Burst
2	2
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that are applied to the requested operation when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the SP-API.

Body Params

Expand All
⬍
The request schema for the CreateShipment operation.

ShipmentRequestDetails
object
required
Shipment information required for requesting shipping service offers or for creating a shipment.


ShipmentRequestDetails object
ShippingServiceId
string
required
An Amazon-defined shipping service identifier.

ShippingServiceOfferId
string
Identifies a shipping service order made by a carrier.

HazmatType
string
enum
Hazardous materials options for a package. Consult the terms and conditions for each carrier for more information on hazardous materials.

Show Details
None	The package does not contain hazardous material.
LQHazmat	The package contains limited quantities of hazardous material.

Allowed:

None

LQHazmat
LabelFormatOption
object
Whether to include a packing slip.


LabelFormatOption object
ShipmentLevelSellerInputsList
array of objects
A list of additional seller input pairs required to purchase shipping.


ADD object
Responses

200
Success.

Response body
object
payload
object
The details of a shipment. Includes the shipment status.

ShipmentId
string
required
An Amazon-defined shipment identifier.

AmazonOrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

SellerOrderId
string
length ≤ 64
A seller-defined order identifier.

ItemList
array of objects
required
The list of items you want to include in a shipment.

object
OrderItemId
string
required
An Amazon-defined identifier for an individual item in an order.

Quantity
int32
required
The number of items.

ItemWeight
object
The weight.


ItemWeight object
ItemDescription
string
The description of the item.

TransparencyCodeList
array of objects
A list of transparency codes.

ItemLevelSellerInputsList
array of objects
A list of additional seller input pairs required to purchase shipping.

object
AdditionalInputFieldName
string
required
The name of the additional input field.

AdditionalSellerInput
object
required
Additional information required to purchase shipping.


AdditionalSellerInput object
LiquidVolume
object
Liquid volume.


LiquidVolume object
IsHazmat
boolean
When true, the item qualifies as hazardous materials (hazmat). Defaults to false.

DangerousGoodsDetails
object
Details related to any dangerous goods or items that are shipped.


DangerousGoodsDetails object
ShipFromAddress
object
required
The postal address information.


ShipFromAddress object
ShipToAddress
object
required
The postal address information.


ShipToAddress object
PackageDimensions
object
required
The dimensions of a package contained in a shipment.


PackageDimensions object
Weight
object
required
The weight.


Weight object
Insurance
object
required
Currency type and amount.


Insurance object
ShippingService
object
required
A shipping service offer made by a carrier.


ShippingService object
Label
object
required
Data for creating a shipping label and dimensions for printing the label.


Label object
Status
string
enum
required
The shipment status.

Purchased RefundPending RefundRejected RefundApplied

Show Details
Purchased	The seller purchased a label by calling the `createShipment` operation.
RefundPending	The seller requested a label refund by calling the `cancelShipment` operation, and the refund request is being processed by the carrier. Note: A seller can create a new shipment for an order while `Status = RefundPending` for a canceled shipment. After you request a label refund (by calling `cancelShipment`), the status of the order remains `Shipped`.
RefundRejected	The label refund request is rejected by the carrier. A refund request is rejected because the cancellation window has expired or the carrier has already accepted the shipment for delivery. Cancellation policies vary by carrier. For more information about carrier cancellation policies, refer to the Seller Central Help for your marketplace.
RefundApplied	The refund has been approved and credited to the seller's account.
TrackingId
string
The shipment tracking identifier provided by the carrier.

CreatedDate
date-time
required
Date-time formatted timestamp.

LastUpdatedDate
date-time
Date-time formatted timestamp.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/mfn/v0/shipments"

payload = { "ShipmentRequestDetails": {
        "Weight": { "Unit": "oz" },
        "ShippingServiceOptions": {
            "DeliveryExperience": "DeliveryConfirmationWithAdultSignature",
            "CarrierWillPickUp": True
        }
    } }
headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)

{
  "payload": {
    "ShipmentId": "string",
    "AmazonOrderId": "string",
    "SellerOrderId": "string",
    "ItemList": [
      {
        "OrderItemId": "string",
        "Quantity": 0,
        "ItemWeight": {
          "Value": 0,
          "Unit": "oz"
        },
        "ItemDescription": "string",
        "TransparencyCodeList": [
          "string"
        ],
        "ItemLevelSellerInputsList": [
          {
            "AdditionalInputFieldName": "string",
            "AdditionalSellerInput": {
              "DataType": "string",
              "ValueAsString": "string",
              "ValueAsBoolean": true,
              "ValueAsInteger": 0,
              "ValueAsTimestamp": "2026-04-21T13:47:20.138Z",
              "ValueAsAddress": {
                "Name": "string",
                "AddressLine1": "string",
                "AddressLine2": "string",
                "AddressLine3": "string",
                "DistrictOrCounty": "string",
                "Email": "string",
                "City": "string",
                "StateOrProvinceCode": "string",
                "PostalCode": "string",
                "CountryCode": "string",
                "Phone": "string"
              },
              "ValueAsWeight": {
                "Value": 0,
                "Unit": "oz"
              },
              "ValueAsDimension": {
                "value": 0,
                "unit": "inches"
              },
              "ValueAsCurrency": {
                "CurrencyCode": "string",
                "Amount": 0
              }
            }
          }
        ],
        "LiquidVolume": {
          "Unit": "ML",
          "Value": 0
        },
        "IsHazmat": true,
        "DangerousGoodsDetails": {
          "UnitedNationsRegulatoryId": "string",
          "TransportationRegulatoryClass": "string",
          "PackingGroup": "I",
          "PackingInstruction": "PI965_SECTION_IA"
        }
      }
    ],
    "ShipFromAddress": {
      "Name": "string",
      "AddressLine1": "string",
      "AddressLine2": "string",
      "AddressLine3": "string",
      "DistrictOrCounty": "string",
      "Email": "string",
      "City": "string",
      "StateOrProvinceCode": "string",
      "PostalCode": "string",
      "CountryCode": "string",
      "Phone": "string"
    },
    "ShipToAddress": {
      "Name": "string",
      "AddressLine1": "string",
      "AddressLine2": "string",
      "AddressLine3": "string",
      "DistrictOrCounty": "string",
      "Email": "string",
      "City": "string",
      "StateOrProvinceCode": "string",
      "PostalCode": "string",
      "CountryCode": "string",
      "Phone": "string"
    },
    "PackageDimensions": {
      "Length": 0,
      "Width": 0,
      "Height": 0,
      "Unit": "inches",
      "PredefinedPackageDimensions": "FedEx_Box_10kg"
    },
    "Weight": {
      "Value": 0,
      "Unit": "oz"
    },
    "Insurance": {
      "CurrencyCode": "string",
      "Amount": 0
    },
    "ShippingService": {
      "ShippingServiceName": "string",
      "CarrierName": "string",
      "ShippingServiceId": "string",
      "ShippingServiceOfferId": "string",
      "ShipDate": "2026-04-21T13:47:20.138Z",
      "EarliestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
      "LatestEstimatedDeliveryDate": "2026-04-21T13:47:20.138Z",
      "Rate": {
        "CurrencyCode": "string",
        "Amount": 0
      },
      "RateWithAdjustments": {
        "CurrencyCode": "string",
        "Amount": 0
      },
      "AdjustmentItemList": [
        {
          "RateItemID": "FBM_SHIP_PLUS_CREDIT",
          "RateItemType": "INCLUDED",
          "RateItemCharge": {
            "CurrencyCode": "string",
            "Amount": 0
          },
          "RateItemNameLocalization": "string"
        }
      ],
      "ShippingServiceOptions": {
        "DeliveryExperience": "DeliveryConfirmationWithAdultSignature",
        "DeclaredValue": {
          "CurrencyCode": "string",
          "Amount": 0
        },
        "CarrierWillPickUp": true,
        "CarrierWillPickUpOption": "CarrierWillPickUp",
        "LabelFormat": "PDF"
      },
      "AvailableShippingServiceOptions": {
        "AvailableCarrierWillPickUpOptions": [
          {
            "CarrierWillPickUpOption": "CarrierWillPickUp",
            "Charge": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          }
        ],
        "AvailableDeliveryExperienceOptions": [
          {
            "DeliveryExperienceOption": "DeliveryConfirmationWithAdultSignature",
            "Charge": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          }
        ]
      },
      "AvailableLabelFormats": [
        "PDF"
      ],
      "AvailableFormatOptionsForLabel": [
        {
          "IncludePackingSlipWithLabel": true,
          "LabelFormat": "PDF"
        }
      ],
      "RequiresAdditionalSellerInputs": true,
      "Benefits": {
        "IncludedBenefits": [
          "string"
        ],
        "ExcludedBenefits": [
          {
            "Benefit": "string",
            "ReasonCodes": [
              "string"
            ]
          }
        ]
      }
    },
    "Label": {
      "CustomTextForLabel": "string",
      "Dimensions": {
        "Length": 0,
        "Width": 0,
        "Unit": "inches"
      },
      "FileContents": {
        "Contents": "string",
        "FileType": "application/pdf",
        "Checksum": "string"
      },
      "LabelFormat": "PDF",
      "StandardIdForLabel": "AmazonOrderId"
    },
    "Status": "Purchased",
    "TrackingId": "string",
    "CreatedDate": "2026-04-21T13:47:20.138Z",
    "LastUpdatedDate": "2026-04-21T13:47:20.138Z"
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

getAdditionalSellerInputs
post
https://sellingpartnerapi-na.amazon.com/mfn/v0/additionalSellerInputs

Gets a list of additional seller inputs required for a ship method. This is generally used for international shipping.

Usage Plan:

Rate (requests per second)	Burst
1	1
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that are applied to the requested operation when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the SP-API.

Body Params

Expand All
⬍
The request schema for the GetAdditionalSellerInputs operation.

ShippingServiceId
string
required
An Amazon-defined shipping service identifier.

ShipFromAddress
object
required
The postal address information.


ShipFromAddress object
OrderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Responses

200
Success.

Response body
object
payload
object
The payload for the getAdditionalSellerInputs operation.

ShipmentLevelFields
array of objects
A list of additional inputs.

object
AdditionalInputFieldName
string
The field name.

SellerInputDefinition
object
Specifies characteristics that apply to a seller input.


SellerInputDefinition object
ItemLevelFieldsList
array of objects
A list of item level fields.

object
Asin
string
required
The Amazon Standard Identification Number (ASIN) of the item.

AdditionalInputs
array of objects
required
A list of additional inputs.

object
AdditionalInputFieldName
string
The field name.

SellerInputDefinition
object
Specifies characteristics that apply to a seller input.


SellerInputDefinition object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/mfn/v0/additionalSellerInputs"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

{
  "payload": {
    "ShipmentLevelFields": [
      {
        "AdditionalInputFieldName": "string",
        "SellerInputDefinition": {
          "IsRequired": true,
          "DataType": "string",
          "Constraints": [
            {
              "ValidationRegEx": "string",
              "ValidationString": "string"
            }
          ],
          "InputDisplayText": "string",
          "InputTarget": "SHIPMENT_LEVEL",
          "StoredValue": {
            "DataType": "string",
            "ValueAsString": "string",
            "ValueAsBoolean": true,
            "ValueAsInteger": 0,
            "ValueAsTimestamp": "2026-04-21T13:47:20.138Z",
            "ValueAsAddress": {
              "Name": "string",
              "AddressLine1": "string",
              "AddressLine2": "string",
              "AddressLine3": "string",
              "DistrictOrCounty": "string",
              "Email": "string",
              "City": "string",
              "StateOrProvinceCode": "string",
              "PostalCode": "string",
              "CountryCode": "string",
              "Phone": "string"
            },
            "ValueAsWeight": {
              "Value": 0,
              "Unit": "oz"
            },
            "ValueAsDimension": {
              "value": 0,
              "unit": "inches"
            },
            "ValueAsCurrency": {
              "CurrencyCode": "string",
              "Amount": 0
            }
          },
          "RestrictedSetValues": [
            "string"
          ]
        }
      }
    ],
    "ItemLevelFieldsList": [
      {
        "Asin": "string",
        "AdditionalInputs": [
          {
            "AdditionalInputFieldName": "string",
            "SellerInputDefinition": {
              "IsRequired": true,
              "DataType": "string",
              "Constraints": [
                {
                  "ValidationRegEx": "string",
                  "ValidationString": "string"
                }
              ],
              "InputDisplayText": "string",
              "InputTarget": "SHIPMENT_LEVEL",
              "StoredValue": {
                "DataType": "string",
                "ValueAsString": "string",
                "ValueAsBoolean": true,
                "ValueAsInteger": 0,
                "ValueAsTimestamp": "2026-04-21T13:47:20.138Z",
                "ValueAsAddress": {
                  "Name": "string",
                  "AddressLine1": "string",
                  "AddressLine2": "string",
                  "AddressLine3": "string",
                  "DistrictOrCounty": "string",
                  "Email": "string",
                  "City": "string",
                  "StateOrProvinceCode": "string",
                  "PostalCode": "string",
                  "CountryCode": "string",
                  "Phone": "string"
                },
                "ValueAsWeight": {
                  "Value": 0,
                  "Unit": "oz"
                },
                "ValueAsDimension": {
                  "value": 0,
                  "unit": "inches"
                },
                "ValueAsCurrency": {
                  "CurrencyCode": "string",
                  "Amount": 0
                }
              },
              "RestrictedSetValues": [
                "string"
              ]
            }
          }
        ]
      }
    ]
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

listFinancialEventGroups
get
https://sellingpartnerapi-na.amazon.com/finances/v0/financialEventGroups

Returns financial event groups for a given date range. Orders from the last 48 hours might not be included in financial events.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput can have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Query Params
MaxResultsPerPage
int32
1 to 100
Defaults to 10
The maximum number of results per page. If the response exceeds the maximum number of transactions or 10 MB, the response is InvalidInput.

10
FinancialEventGroupStartedBefore
date-time
A date that selects financial event groups that opened before (but not at) a specified date and time, in ISO 8601 format. The date-time must be after FinancialEventGroupStartedAfter and more than two minutes before the time of request. If FinancialEventGroupStartedAfter and FinancialEventGroupStartedBefore are more than 180 days apart, no financial event groups are returned.

FinancialEventGroupStartedAfter
date-time
A date that selects financial event groups that opened after (or at) a specified date and time, in ISO 8601 format. The date-time must be more than two minutes before you submit the request.

NextToken
string
The response includes nextToken when the number of results exceeds the specified pageSize value. To get the next page of results, call the operation with this token and include the same arguments as the call that produced the token. To get a complete list, call this operation until nextToken is null. Note that this operation can return empty pages.

Responses

200
Success.

Response body
object
payload
object
The payload for the listFinancialEventGroups operation.

NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

FinancialEventGroupList
array of objects
A list of financial event group information.

object
FinancialEventGroupId
string
A unique identifier for the financial event group.

ProcessingStatus
string
The processing status of the financial event group indicates whether the balance of the financial event group is settled.

Possible values:

Open
Closed
FundTransferStatus
string
The status of the fund transfer.

OriginalTotal
object
A currency type and amount.


OriginalTotal object
ConvertedTotal
object
A currency type and amount.


ConvertedTotal object
FundTransferDate
date-time
A date in ISO 8601 date-time format.

TraceId
string
The trace identifier used by sellers to look up transactions externally.

AccountTail
string
The account tail of the payment instrument.

BeginningBalance
object
A currency type and amount.


BeginningBalance object
FinancialEventGroupStart
date-time
A date in ISO 8601 date-time format.

FinancialEventGroupEnd
date-time
A date in ISO 8601 date-time format.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request GET \
     --url 'https://sellingpartnerapi-na.amazon.com/finances/v0/financialEventGroups?MaxResultsPerPage=10' \
     --header 'accept: application/json'

     {
  "payload": {
    "NextToken": "string",
    "FinancialEventGroupList": [
      {
        "FinancialEventGroupId": "string",
        "ProcessingStatus": "string",
        "FundTransferStatus": "string",
        "OriginalTotal": {
          "CurrencyCode": "string",
          "CurrencyAmount": 0
        },
        "ConvertedTotal": {
          "CurrencyCode": "string",
          "CurrencyAmount": 0
        },
        "FundTransferDate": "2026-04-21T13:49:34.489Z",
        "TraceId": "string",
        "AccountTail": "string",
        "BeginningBalance": {
          "CurrencyCode": "string",
          "CurrencyAmount": 0
        },
        "FinancialEventGroupStart": "2026-04-21T13:49:34.489Z",
        "FinancialEventGroupEnd": "2026-04-21T13:49:34.489Z"
      }
    ]
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

listFinancialEventsByGroupId
get
https://sellingpartnerapi-na.amazon.com/finances/v0/financialEventGroups/{eventGroupId}/financialEvents

Returns all financial events for the specified financial event group. Orders from the last 48 hours might not be included in financial events.

Note: This operation only retrieves a group's data for the past two years. A request for data spanning more than two years produces an empty response.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput can have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
eventGroupId
string
required
The identifier of the financial event group to which the events belong.

Query Params
MaxResultsPerPage
int32
1 to 100
Defaults to 100
The maximum number of results to return per page. If the response exceeds the maximum number of transactions or 10 MB, the response is InvalidInput.

100
PostedAfter
date-time
The response includes financial events posted after (or on) this date. This date must be in ISO 8601 date-time format. The date-time must be more than two minutes before the time of the request.

PostedBefore
date-time
The response includes financial events posted before (but not on) this date. This date must be in ISO 8601 date-time format.

The date-time must be later than PostedAfter and more than two minutes before the request was submitted. If PostedAfter and PostedBefore are more than 180 days apart, the response is empty. If you include the PostedBefore parameter in your request, you must also specify the PostedAfter parameter.

Default: Two minutes before the time of the request.

NextToken
string
The response includes nextToken when the number of results exceeds the specified pageSize value. To get the next page of results, call the operation with this token and include the same arguments as the call that produced the token. To get a complete list, call this operation until nextToken is null. Note that this operation can return empty pages.

Responses

200
Success.

Response body
object
payload
object
The payload for the listFinancialEvents operation.

NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

FinancialEvents
object
All the information that is related to a financial event.


FinancialEvents object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request GET \
     --url 'https://sellingpartnerapi-na.amazon.com/finances/v0/financialEventGroups/eventGroupId/financialEvents?MaxResultsPerPage=100' \
     --header 'accept: application/json'

     {
  "payload": {
    "NextToken": "string",
    "FinancialEvents": {
      "ShipmentEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "ShipmentSettleEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "RefundEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "GuaranteeClaimEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "EBTRefundReimbursementOnlyEventList": [
        {
          "OrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Amount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ChargebackEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "PayWithAmazonEventList": [
        {
          "SellerOrderId": "string",
          "TransactionPostedDate": "2026-04-21T13:49:34.489Z",
          "BusinessObjectType": "string",
          "SalesChannel": "string",
          "Charge": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PaymentAmountType": "string",
          "AmountDescription": "string",
          "FulfillmentChannel": "string",
          "StoreName": "string"
        }
      ],
      "ServiceProviderCreditEventList": [
        {
          "ProviderTransactionType": "string",
          "SellerOrderId": "string",
          "MarketplaceId": "string",
          "MarketplaceCountryCode": "string",
          "SellerId": "string",
          "SellerStoreName": "string",
          "ProviderId": "string",
          "ProviderStoreName": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TransactionCreationDate": "2026-04-21T13:49:34.489Z"
        }
      ],
      "RetrochargeEventList": [
        {
          "RetrochargeEventType": "string",
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "BaseTax": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "ShippingTax": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "MarketplaceName": "string",
          "RetrochargeTaxWithheldList": [
            {
              "TaxCollectionModel": "string",
              "TaxesWithheld": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ]
            }
          ]
        }
      ],
      "RentalTransactionEventList": [
        {
          "AmazonOrderId": "string",
          "RentalEventType": "string",
          "ExtensionLength": 0,
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "RentalChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "RentalFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "MarketplaceName": "string",
          "RentalInitialValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "RentalReimbursement": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "RentalTaxWithheldList": [
            {
              "TaxCollectionModel": "string",
              "TaxesWithheld": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ]
            }
          ]
        }
      ],
      "ProductAdsPaymentEventList": [
        {
          "postedDate": "2026-04-21T13:49:34.489Z",
          "transactionType": "string",
          "invoiceId": "string",
          "baseValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "taxValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "transactionValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ServiceFeeEventList": [
        {
          "AmazonOrderId": "string",
          "FeeReason": "string",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "SellerSKU": "string",
          "FnSKU": "string",
          "FeeDescription": "string",
          "ASIN": "string",
          "StoreName": "string"
        }
      ],
      "SellerDealPaymentEventList": [
        {
          "postedDate": "2026-04-21T13:49:34.489Z",
          "dealId": "string",
          "dealDescription": "string",
          "eventType": "string",
          "feeType": "string",
          "feeAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "taxAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "totalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "DebtRecoveryEventList": [
        {
          "DebtRecoveryType": "string",
          "RecoveryAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "OverPaymentCredit": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "DebtRecoveryItemList": [
            {
              "RecoveryAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "OriginalAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "GroupBeginDate": "2026-04-21T13:49:34.489Z",
              "GroupEndDate": "2026-04-21T13:49:34.489Z"
            }
          ],
          "ChargeInstrumentList": [
            {
              "Description": "string",
              "Tail": "string",
              "Amount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "LoanServicingEventList": [
        {
          "LoanAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "SourceBusinessEventType": "string"
        }
      ],
      "AdjustmentEventList": [
        {
          "AdjustmentType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "StoreName": "string",
          "AdjustmentAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "AdjustmentItemList": [
            {
              "Quantity": "string",
              "PerUnitAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TotalAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "SellerSKU": "string",
              "FnSKU": "string",
              "ProductDescription": "string",
              "ASIN": "string",
              "TransactionNumber": "string"
            }
          ]
        }
      ],
      "SAFETReimbursementEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "SAFETClaimId": "string",
          "ReimbursedAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "ReasonCode": "string",
          "SAFETReimbursementItemList": [
            {
              "itemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "productDescription": "string",
              "quantity": "string"
            }
          ]
        }
      ],
      "SellerReviewEnrollmentPaymentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "EnrollmentId": "string",
          "ParentASIN": "string",
          "FeeComponent": {
            "FeeType": "string",
            "FeeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "ChargeComponent": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "TotalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "FBALiquidationEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "OriginalRemovalOrderId": "string",
          "LiquidationProceedsAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "LiquidationFeeAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "CouponPaymentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "CouponId": "string",
          "SellerCouponDescription": "string",
          "ClipOrRedemptionCount": 0,
          "PaymentEventId": "string",
          "FeeComponent": {
            "FeeType": "string",
            "FeeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "ChargeComponent": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "TotalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ImagingServicesFeeEventList": [
        {
          "ImagingRequestBillingItemID": "string",
          "ASIN": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "NetworkComminglingTransactionEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "NetCoTransactionID": "string",
          "SwapReason": "string",
          "ASIN": "string",
          "MarketplaceId": "string",
          "TaxExclusiveAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AffordabilityExpenseEventList": [
        {
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MarketplaceId": "string",
          "TransactionType": "string",
          "BaseExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeCGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeSGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeIGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TotalExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AffordabilityExpenseReversalEventList": [
        {
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MarketplaceId": "string",
          "TransactionType": "string",
          "BaseExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeCGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeSGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeIGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TotalExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "RemovalShipmentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MerchantOrderId": "string",
          "OrderId": "string",
          "TransactionType": "string",
          "StoreName": "string",
          "RemovalShipmentItemList": [
            {
              "RemovalShipmentItemId": "string",
              "TaxCollectionModel": "string",
              "FulfillmentNetworkSKU": "string",
              "Quantity": 0,
              "Revenue": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxWithheld": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "RemovalShipmentAdjustmentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "AdjustmentEventId": "string",
          "MerchantOrderId": "string",
          "OrderId": "string",
          "TransactionType": "string",
          "RemovalShipmentItemAdjustmentList": [
            {
              "RemovalShipmentItemId": "string",
              "TaxCollectionModel": "string",
              "FulfillmentNetworkSKU": "string",
              "AdjustedQuantity": 0,
              "RevenueAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxAmountAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxWithheldAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "TrialShipmentEventList": [
        {
          "AmazonOrderId": "string",
          "FinancialEventGroupId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "SKU": "string",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "TDSReimbursementEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "TDSOrderId": "string",
          "ReimbursedAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AdhocDisbursementEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "TransactionId": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "TaxWithholdingEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "BaseAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "WithheldAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxWithholdingPeriod": {
            "StartDate": "2026-04-21T13:49:34.489Z",
            "EndDate": "2026-04-21T13:49:34.489Z"
          }
        }
      ],
      "ChargeRefundEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ReasonCode": "string",
          "ReasonCodeDescription": "string",
          "ChargeRefundTransactions": [
            {
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "ChargeType": "string"
            }
          ]
        }
      ],
      "FailedAdhocDisbursementEventList": [
        {
          "FundsTransfersType": "string",
          "TransferId": "string",
          "DisbursementId": "string",
          "PaymentDisbursementType": "string",
          "Status": "string",
          "TransferAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "PostedDate": "2026-04-21T13:49:34.489Z"
        }
      ],
      "ValueAddedServiceChargeEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Description": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "CapacityReservationBillingEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Description": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ]
    }
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

listFinancialEventsByOrderId
get
https://sellingpartnerapi-na.amazon.com/finances/v0/orders/{orderId}/financialEvents

Returns all financial events for the specified order. Orders from the last 48 hours might not be included in financial events.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput can have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Path Params
orderId
string
required
An Amazon-defined order identifier, in 3-7-7 format.

Query Params
MaxResultsPerPage
int32
1 to 100
Defaults to 100
The maximum number of results to return per page. If the response exceeds the maximum number of transactions or 10 MB, the response is InvalidInput.

100
NextToken
string
The response includes nextToken when the number of results exceeds the specified pageSize value. To get the next page of results, call the operation with this token and include the same arguments as the call that produced the token. To get a complete list, call this operation until nextToken is null. Note that this operation can return empty pages.

Responses

200
Financial Events successfully retrieved.

Response body
object
payload
object
The payload for the listFinancialEvents operation.

NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

FinancialEvents
object
All the information that is related to a financial event.


FinancialEvents object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request GET \
     --url 'https://sellingpartnerapi-na.amazon.com/finances/v0/orders/orderId/financialEvents?MaxResultsPerPage=100' \
     --header 'accept: application/json'

     {
  "payload": {
    "NextToken": "string",
    "FinancialEvents": {
      "ShipmentEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "ShipmentSettleEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "RefundEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "GuaranteeClaimEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "EBTRefundReimbursementOnlyEventList": [
        {
          "OrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Amount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ChargebackEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "PayWithAmazonEventList": [
        {
          "SellerOrderId": "string",
          "TransactionPostedDate": "2026-04-21T13:49:34.489Z",
          "BusinessObjectType": "string",
          "SalesChannel": "string",
          "Charge": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PaymentAmountType": "string",
          "AmountDescription": "string",
          "FulfillmentChannel": "string",
          "StoreName": "string"
        }
      ],
      "ServiceProviderCreditEventList": [
        {
          "ProviderTransactionType": "string",
          "SellerOrderId": "string",
          "MarketplaceId": "string",
          "MarketplaceCountryCode": "string",
          "SellerId": "string",
          "SellerStoreName": "string",
          "ProviderId": "string",
          "ProviderStoreName": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TransactionCreationDate": "2026-04-21T13:49:34.489Z"
        }
      ],
      "RetrochargeEventList": [
        {
          "RetrochargeEventType": "string",
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "BaseTax": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "ShippingTax": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "MarketplaceName": "string",
          "RetrochargeTaxWithheldList": [
            {
              "TaxCollectionModel": "string",
              "TaxesWithheld": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ]
            }
          ]
        }
      ],
      "RentalTransactionEventList": [
        {
          "AmazonOrderId": "string",
          "RentalEventType": "string",
          "ExtensionLength": 0,
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "RentalChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "RentalFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "MarketplaceName": "string",
          "RentalInitialValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "RentalReimbursement": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "RentalTaxWithheldList": [
            {
              "TaxCollectionModel": "string",
              "TaxesWithheld": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ]
            }
          ]
        }
      ],
      "ProductAdsPaymentEventList": [
        {
          "postedDate": "2026-04-21T13:49:34.489Z",
          "transactionType": "string",
          "invoiceId": "string",
          "baseValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "taxValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "transactionValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ServiceFeeEventList": [
        {
          "AmazonOrderId": "string",
          "FeeReason": "string",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "SellerSKU": "string",
          "FnSKU": "string",
          "FeeDescription": "string",
          "ASIN": "string",
          "StoreName": "string"
        }
      ],
      "SellerDealPaymentEventList": [
        {
          "postedDate": "2026-04-21T13:49:34.489Z",
          "dealId": "string",
          "dealDescription": "string",
          "eventType": "string",
          "feeType": "string",
          "feeAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "taxAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "totalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "DebtRecoveryEventList": [
        {
          "DebtRecoveryType": "string",
          "RecoveryAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "OverPaymentCredit": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "DebtRecoveryItemList": [
            {
              "RecoveryAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "OriginalAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "GroupBeginDate": "2026-04-21T13:49:34.489Z",
              "GroupEndDate": "2026-04-21T13:49:34.489Z"
            }
          ],
          "ChargeInstrumentList": [
            {
              "Description": "string",
              "Tail": "string",
              "Amount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "LoanServicingEventList": [
        {
          "LoanAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "SourceBusinessEventType": "string"
        }
      ],
      "AdjustmentEventList": [
        {
          "AdjustmentType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "StoreName": "string",
          "AdjustmentAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "AdjustmentItemList": [
            {
              "Quantity": "string",
              "PerUnitAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TotalAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "SellerSKU": "string",
              "FnSKU": "string",
              "ProductDescription": "string",
              "ASIN": "string",
              "TransactionNumber": "string"
            }
          ]
        }
      ],
      "SAFETReimbursementEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "SAFETClaimId": "string",
          "ReimbursedAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "ReasonCode": "string",
          "SAFETReimbursementItemList": [
            {
              "itemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "productDescription": "string",
              "quantity": "string"
            }
          ]
        }
      ],
      "SellerReviewEnrollmentPaymentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "EnrollmentId": "string",
          "ParentASIN": "string",
          "FeeComponent": {
            "FeeType": "string",
            "FeeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "ChargeComponent": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "TotalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "FBALiquidationEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "OriginalRemovalOrderId": "string",
          "LiquidationProceedsAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "LiquidationFeeAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "CouponPaymentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "CouponId": "string",
          "SellerCouponDescription": "string",
          "ClipOrRedemptionCount": 0,
          "PaymentEventId": "string",
          "FeeComponent": {
            "FeeType": "string",
            "FeeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "ChargeComponent": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "TotalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ImagingServicesFeeEventList": [
        {
          "ImagingRequestBillingItemID": "string",
          "ASIN": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "NetworkComminglingTransactionEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "NetCoTransactionID": "string",
          "SwapReason": "string",
          "ASIN": "string",
          "MarketplaceId": "string",
          "TaxExclusiveAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AffordabilityExpenseEventList": [
        {
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MarketplaceId": "string",
          "TransactionType": "string",
          "BaseExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeCGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeSGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeIGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TotalExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AffordabilityExpenseReversalEventList": [
        {
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MarketplaceId": "string",
          "TransactionType": "string",
          "BaseExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeCGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeSGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeIGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TotalExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "RemovalShipmentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MerchantOrderId": "string",
          "OrderId": "string",
          "TransactionType": "string",
          "StoreName": "string",
          "RemovalShipmentItemList": [
            {
              "RemovalShipmentItemId": "string",
              "TaxCollectionModel": "string",
              "FulfillmentNetworkSKU": "string",
              "Quantity": 0,
              "Revenue": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxWithheld": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "RemovalShipmentAdjustmentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "AdjustmentEventId": "string",
          "MerchantOrderId": "string",
          "OrderId": "string",
          "TransactionType": "string",
          "RemovalShipmentItemAdjustmentList": [
            {
              "RemovalShipmentItemId": "string",
              "TaxCollectionModel": "string",
              "FulfillmentNetworkSKU": "string",
              "AdjustedQuantity": 0,
              "RevenueAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxAmountAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxWithheldAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "TrialShipmentEventList": [
        {
          "AmazonOrderId": "string",
          "FinancialEventGroupId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "SKU": "string",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "TDSReimbursementEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "TDSOrderId": "string",
          "ReimbursedAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AdhocDisbursementEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "TransactionId": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "TaxWithholdingEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "BaseAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "WithheldAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxWithholdingPeriod": {
            "StartDate": "2026-04-21T13:49:34.489Z",
            "EndDate": "2026-04-21T13:49:34.489Z"
          }
        }
      ],
      "ChargeRefundEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ReasonCode": "string",
          "ReasonCodeDescription": "string",
          "ChargeRefundTransactions": [
            {
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "ChargeType": "string"
            }
          ]
        }
      ],
      "FailedAdhocDisbursementEventList": [
        {
          "FundsTransfersType": "string",
          "TransferId": "string",
          "DisbursementId": "string",
          "PaymentDisbursementType": "string",
          "Status": "string",
          "TransferAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "PostedDate": "2026-04-21T13:49:34.489Z"
        }
      ],
      "ValueAddedServiceChargeEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Description": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "CapacityReservationBillingEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Description": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ]
    }
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

listFinancialEvents
get
https://sellingpartnerapi-na.amazon.com/finances/v0/financialEvents

Returns financial events for the specified data range. Orders from the last 48 hours might not be included in financial events.

Note: in ListFinancialEvents, deferred events don't show up in responses until they are released.

Usage Plan:

Rate (requests per second)	Burst
0.5	30
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput can have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Query Params
MaxResultsPerPage
int32
1 to 100
Defaults to 100
The maximum number of results to return per page. If the response exceeds the maximum number of transactions or 10 MB, the response is InvalidInput.

100
PostedAfter
date-time
The response includes financial events posted after (or on) this date. This date must be in ISO 8601 date-time format. The date-time must be more than two minutes before the time of the request.

PostedBefore
date-time
The response includes financial events posted before (but not on) this date. This date must be in ISO 8601 date-time format.

The date-time must be later than PostedAfter and more than two minutes before the request was submitted. If PostedAfter and PostedBefore are more than 180 days apart, the response is empty. If you include the PostedBefore parameter in your request, you must also specify the PostedAfter parameter.

Default: Two minutes before the time of the request.

NextToken
string
The response includes nextToken when the number of results exceeds the specified pageSize value. To get the next page of results, call the operation with this token and include the same arguments as the call that produced the token. To get a complete list, call this operation until nextToken is null. Note that this operation can return empty pages.

Responses

200
Success.

Response body
object
payload
object
The payload for the listFinancialEvents operation.

NextToken
string
When present and not empty, pass this string token in the next request to return the next response page.

FinancialEvents
object
All the information that is related to a financial event.


FinancialEvents object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help the caller understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request GET \
     --url 'https://sellingpartnerapi-na.amazon.com/finances/v0/financialEvents?MaxResultsPerPage=100' \
     --header 'accept: application/json'

     {
  "payload": {
    "NextToken": "string",
    "FinancialEvents": {
      "ShipmentEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "ShipmentSettleEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "RefundEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "GuaranteeClaimEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "EBTRefundReimbursementOnlyEventList": [
        {
          "OrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Amount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ChargebackEventList": [
        {
          "AmazonOrderId": "string",
          "SellerOrderId": "string",
          "MarketplaceName": "string",
          "StoreName": "string",
          "OrderChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderChargeAdjustmentList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "OrderFeeAdjustmentList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "DirectPaymentList": [
            {
              "DirectPaymentType": "string",
              "DirectPaymentAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ShipmentItemList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "ShipmentItemAdjustmentList": [
            {
              "SellerSKU": "string",
              "OrderItemId": "string",
              "OrderAdjustmentItemId": "string",
              "QuantityShipped": 0,
              "ItemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemChargeAdjustmentList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemFeeAdjustmentList": [
                {
                  "FeeType": "string",
                  "FeeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "ItemTaxWithheldList": [
                {
                  "TaxCollectionModel": "string",
                  "TaxesWithheld": [
                    {
                      "ChargeType": "string",
                      "ChargeAmount": {
                        "CurrencyCode": "string",
                        "CurrencyAmount": 0
                      }
                    }
                  ]
                }
              ],
              "PromotionList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "PromotionAdjustmentList": [
                {
                  "PromotionType": "string",
                  "PromotionId": "string",
                  "PromotionAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "CostOfPointsGranted": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "CostOfPointsReturned": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "PayWithAmazonEventList": [
        {
          "SellerOrderId": "string",
          "TransactionPostedDate": "2026-04-21T13:49:34.489Z",
          "BusinessObjectType": "string",
          "SalesChannel": "string",
          "Charge": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "PaymentAmountType": "string",
          "AmountDescription": "string",
          "FulfillmentChannel": "string",
          "StoreName": "string"
        }
      ],
      "ServiceProviderCreditEventList": [
        {
          "ProviderTransactionType": "string",
          "SellerOrderId": "string",
          "MarketplaceId": "string",
          "MarketplaceCountryCode": "string",
          "SellerId": "string",
          "SellerStoreName": "string",
          "ProviderId": "string",
          "ProviderStoreName": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TransactionCreationDate": "2026-04-21T13:49:34.489Z"
        }
      ],
      "RetrochargeEventList": [
        {
          "RetrochargeEventType": "string",
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "BaseTax": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "ShippingTax": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "MarketplaceName": "string",
          "RetrochargeTaxWithheldList": [
            {
              "TaxCollectionModel": "string",
              "TaxesWithheld": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ]
            }
          ]
        }
      ],
      "RentalTransactionEventList": [
        {
          "AmazonOrderId": "string",
          "RentalEventType": "string",
          "ExtensionLength": 0,
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "RentalChargeList": [
            {
              "ChargeType": "string",
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "RentalFeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "MarketplaceName": "string",
          "RentalInitialValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "RentalReimbursement": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "RentalTaxWithheldList": [
            {
              "TaxCollectionModel": "string",
              "TaxesWithheld": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ]
            }
          ]
        }
      ],
      "ProductAdsPaymentEventList": [
        {
          "postedDate": "2026-04-21T13:49:34.489Z",
          "transactionType": "string",
          "invoiceId": "string",
          "baseValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "taxValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "transactionValue": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ServiceFeeEventList": [
        {
          "AmazonOrderId": "string",
          "FeeReason": "string",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ],
          "SellerSKU": "string",
          "FnSKU": "string",
          "FeeDescription": "string",
          "ASIN": "string",
          "StoreName": "string"
        }
      ],
      "SellerDealPaymentEventList": [
        {
          "postedDate": "2026-04-21T13:49:34.489Z",
          "dealId": "string",
          "dealDescription": "string",
          "eventType": "string",
          "feeType": "string",
          "feeAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "taxAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "totalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "DebtRecoveryEventList": [
        {
          "DebtRecoveryType": "string",
          "RecoveryAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "OverPaymentCredit": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "DebtRecoveryItemList": [
            {
              "RecoveryAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "OriginalAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "GroupBeginDate": "2026-04-21T13:49:34.489Z",
              "GroupEndDate": "2026-04-21T13:49:34.489Z"
            }
          ],
          "ChargeInstrumentList": [
            {
              "Description": "string",
              "Tail": "string",
              "Amount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "LoanServicingEventList": [
        {
          "LoanAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "SourceBusinessEventType": "string"
        }
      ],
      "AdjustmentEventList": [
        {
          "AdjustmentType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "StoreName": "string",
          "AdjustmentAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "AdjustmentItemList": [
            {
              "Quantity": "string",
              "PerUnitAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TotalAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "SellerSKU": "string",
              "FnSKU": "string",
              "ProductDescription": "string",
              "ASIN": "string",
              "TransactionNumber": "string"
            }
          ]
        }
      ],
      "SAFETReimbursementEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "SAFETClaimId": "string",
          "ReimbursedAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "ReasonCode": "string",
          "SAFETReimbursementItemList": [
            {
              "itemChargeList": [
                {
                  "ChargeType": "string",
                  "ChargeAmount": {
                    "CurrencyCode": "string",
                    "CurrencyAmount": 0
                  }
                }
              ],
              "productDescription": "string",
              "quantity": "string"
            }
          ]
        }
      ],
      "SellerReviewEnrollmentPaymentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "EnrollmentId": "string",
          "ParentASIN": "string",
          "FeeComponent": {
            "FeeType": "string",
            "FeeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "ChargeComponent": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "TotalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "FBALiquidationEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "OriginalRemovalOrderId": "string",
          "LiquidationProceedsAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "LiquidationFeeAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "CouponPaymentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "CouponId": "string",
          "SellerCouponDescription": "string",
          "ClipOrRedemptionCount": 0,
          "PaymentEventId": "string",
          "FeeComponent": {
            "FeeType": "string",
            "FeeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "ChargeComponent": {
            "ChargeType": "string",
            "ChargeAmount": {
              "CurrencyCode": "string",
              "CurrencyAmount": 0
            }
          },
          "TotalAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "ImagingServicesFeeEventList": [
        {
          "ImagingRequestBillingItemID": "string",
          "ASIN": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "NetworkComminglingTransactionEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "NetCoTransactionID": "string",
          "SwapReason": "string",
          "ASIN": "string",
          "MarketplaceId": "string",
          "TaxExclusiveAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AffordabilityExpenseEventList": [
        {
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MarketplaceId": "string",
          "TransactionType": "string",
          "BaseExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeCGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeSGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeIGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TotalExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AffordabilityExpenseReversalEventList": [
        {
          "AmazonOrderId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MarketplaceId": "string",
          "TransactionType": "string",
          "BaseExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeCGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeSGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxTypeIGST": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TotalExpense": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "RemovalShipmentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "MerchantOrderId": "string",
          "OrderId": "string",
          "TransactionType": "string",
          "StoreName": "string",
          "RemovalShipmentItemList": [
            {
              "RemovalShipmentItemId": "string",
              "TaxCollectionModel": "string",
              "FulfillmentNetworkSKU": "string",
              "Quantity": 0,
              "Revenue": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxWithheld": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "RemovalShipmentAdjustmentEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "AdjustmentEventId": "string",
          "MerchantOrderId": "string",
          "OrderId": "string",
          "TransactionType": "string",
          "RemovalShipmentItemAdjustmentList": [
            {
              "RemovalShipmentItemId": "string",
              "TaxCollectionModel": "string",
              "FulfillmentNetworkSKU": "string",
              "AdjustedQuantity": 0,
              "RevenueAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxAmountAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "TaxWithheldAdjustment": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "TrialShipmentEventList": [
        {
          "AmazonOrderId": "string",
          "FinancialEventGroupId": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "SKU": "string",
          "FeeList": [
            {
              "FeeType": "string",
              "FeeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              }
            }
          ]
        }
      ],
      "TDSReimbursementEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "TDSOrderId": "string",
          "ReimbursedAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "AdhocDisbursementEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "TransactionId": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "TaxWithholdingEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "BaseAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "WithheldAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "TaxWithholdingPeriod": {
            "StartDate": "2026-04-21T13:49:34.489Z",
            "EndDate": "2026-04-21T13:49:34.489Z"
          }
        }
      ],
      "ChargeRefundEventList": [
        {
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "ReasonCode": "string",
          "ReasonCodeDescription": "string",
          "ChargeRefundTransactions": [
            {
              "ChargeAmount": {
                "CurrencyCode": "string",
                "CurrencyAmount": 0
              },
              "ChargeType": "string"
            }
          ]
        }
      ],
      "FailedAdhocDisbursementEventList": [
        {
          "FundsTransfersType": "string",
          "TransferId": "string",
          "DisbursementId": "string",
          "PaymentDisbursementType": "string",
          "Status": "string",
          "TransferAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          },
          "PostedDate": "2026-04-21T13:49:34.489Z"
        }
      ],
      "ValueAddedServiceChargeEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Description": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ],
      "CapacityReservationBillingEventList": [
        {
          "TransactionType": "string",
          "PostedDate": "2026-04-21T13:49:34.489Z",
          "Description": "string",
          "TransactionAmount": {
            "CurrencyCode": "string",
            "CurrencyAmount": 0
          }
        }
      ]
    }
  },
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}

listTransactions
get
https://sellingpartnerapi-na.amazon.com/finances/2024-06-19/transactions

Returns transactions for the given parameters. Financial events might not include orders from the last 48 hours.

Usage plan:

Rate (requests per second)	Burst
0.5	10
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

❗️
To view the response

The response to this operation cannot be displayed in this reference because of technical issues. For this operation's response schema, refer to listTransactions.

Query Params
postedAfter
date-time
The response includes financial events posted on or after this date. This date must be in ISO 8601 date-time format. The date-time must be more than two minutes before the time of the request.

This field is required if you do not specify a related identifier.

postedBefore
date-time
The response includes financial events posted before (but not on) this date. This date must be in ISO 8601 date-time format.

The date-time must be later than PostedAfter and more than two minutes before the request was submitted. If PostedAfter and PostedBefore are more than 180 days apart, the response is empty.

Default: Two minutes before the time of the request.

marketplaceId
string
The identifier of the marketplace from which you want to retrieve transactions. The marketplace ID is the globally unique identifier of a marketplace. To find the ID for your marketplace, refer to Marketplace IDs.

transactionStatus
string
The status of the transaction.

Possible values:

DEFERRED: the transaction is currently deferred.
RELEASED: the transaction is currently released.
DEFERRED_RELEASED: the transaction was deferred in the past, but is now released. The status of a deferred transaction is updated to DEFERRED_RELEASED when the transaction is released.
relatedIdentifierName
string
The name of the relatedIdentifier.

Possible values:

FINANCIAL_EVENT_GROUP_ID: the financial event group ID associated with the transaction.

ORDER_ID: the order ID associated with the transaction.

Note:

FINANCIAL_EVENT_GROUP_ID and ORDER_ID are the only relatedIdentifier with filtering capabilities at the moment. While other relatedIdentifier values will be included in the response when available, they cannot be used for filtering purposes.

relatedIdentifierValue
string
The value of the relatedIdentifier.

nextToken
string
The response includes nextToken when the number of results exceeds the specified pageSize value. To get the next page of results, call the operation with this token and include the same arguments as the call that produced the token. To get a complete list, call this operation until nextToken is null. Note that this operation can return empty pages.

Responses

200
Success.

Response body
object
payload
object
The payload for the listTransactions operation.

nextToken
string
The response includes nextToken when the number of results exceeds the specified pageSize value. To get the next page of results, call the operation with this token and include the same arguments as the call that produced the token. To get a complete list, call this operation until nextToken is null. Note that this operation can return empty pages.

transactions
array of objects
A list of transactions within the specified time period.


Transaction object
Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request GET \
     --url https://sellingpartnerapi-na.amazon.com/finances/2024-06-19/transactions \
     --header 'accept: application/json'

     {
  "payload": {
    "nextToken": "string",
    "transactions": [
      {
        "sellingPartnerMetadata": {
          "sellingPartnerId": "XXXXXXXXXXXXXX",
          "accountType": "PAYABLE",
          "marketplaceId": "ATVPDKIKX0DER"
        },
        "relatedIdentifiers": [
          {
            "relatedIdentifierName": "ORDER_ID",
            "relatedIdentifierValue": "8129762527551"
          }
        ],
        "transactionType": "Shipment",
        "transactionId": "b1qD0oAliFkLiqRyGbmeT0DoS2Z2kHzi7TZ92z-vARI",
        "transactionStatus": "Released",
        "description": "Order Payment",
        "postedDate": "2020-07-14T03:35:13.214Z",
        "totalAmount": {
          "currencyAmount": 10,
          "currencyCode": "USD"
        },
        "marketplaceDetails": {
          "marketplaceId": "ATVPDKIKX0DER",
          "marketplaceName": "Amazon.com"
        },
        "items": [
          {
            "description": "Item title",
            "totalAmount": {
              "currencyAmount": 10,
              "currencyCode": "USD"
            },
            "relatedIdentifiers": [
              {
                "itemRelatedIdentifierName": "ORDER_ADJUSTMENT_ITEM_ID",
                "itemRelatedIdentifierValue": "81297625-121-27551"
              }
            ],
            "breakdowns": [
              {
                "breakdownType": "Product Charges",
                "breakdownAmount": {
                  "currencyAmount": 10,
                  "currencyCode": "USD"
                },
                "breakdowns": [
                  {
                    "breakdownType": "Principle",
                    "breakdownAmount": {
                      "currencyAmount": 10,
                      "currencyCode": "USD"
                    },
                    "breakdowns": []
                  }
                ]
              }
            ],
            "contexts": [
              {
                "contextType": "ProductContext",
                "asin": "B07FGXZQZ1",
                "sku": "sku-12",
                "quantityShipped": 1,
                "fulfillmentNetwork": "MFN"
              }
            ]
          }
        ],
        "breakdowns": {
          "breakdowns": [
            {
              "breakdownType": "Sales",
              "breakdownAmount": {
                "currencyAmount": 10,
                "currencyCode": "USD"
              },
              "breakdowns": [
                {
                  "breakdownType": "Product Charges",
                  "breakdownAmount": {
                    "currencyAmount": 10,
                    "currencyCode": "USD"
                  },
                  "breakdowns": []
                }
              ]
            }
          ]
        },
        "contexts": [
          {
            "contextType": "AmazonPayContext",
            "storeName": "Store 1",
            "orderType": "Order Type",
            "channel": "MFN"
          }
        ]
      }
    ]
  }
}

initiatePayout
post
https://sellingpartnerapi-na.amazon.com/finances/transfers/2024-06-01/payouts

Initiates an on-demand payout to the seller's default deposit method in Seller Central for the given marketplaceId and accountType, if eligible. You can only initiate one on-demand payout for each marketplace and account type within a 24-hour period.

Usage Plan:

Rate (requests per second)	Burst
0.017	2
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Body Params

Expand All
⬍
The request body for the initiatePayout operation.

marketplaceId
string
required
The identifier of the Amazon marketplace. For the list of all marketplace IDs, refer to Marketplace IDs.

accountType
string
required
The account type in the selected marketplace for which a payout must be initiated. For supported EU marketplaces, the only account type is Standard Orders.

Responses

200
Success.

Response body
object
payoutReferenceId
string
required
The financial event group ID for a successfully initiated payout. You can use this ID to track payout information.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request POST \
     --url https://sellingpartnerapi-na.amazon.com/finances/transfers/2024-06-01/payouts \
     --header 'accept: application/json' \
     --header 'content-type: application/json'

     {
  "payoutReferenceId": "3DM7DQi8DPAMOLOSaN5HxT0q2waNwH95fopx3AD2Lgc"
}

getPaymentMethods
get
https://sellingpartnerapi-na.amazon.com/finances/transfers/2024-06-01/paymentMethods

Returns the list of payment methods for the seller, which can be filtered by method type.

Usage Plan:

Rate (requests per second)	Burst
.5	30
The x-amzn-RateLimit-Limit response header contains the usage plan rate limits for the operation, when available. The preceding table contains the default rate and burst values for this operation. Selling partners whose business demands require higher throughput might have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits.

Query Params
marketplaceId
string
required
The identifier of the marketplace from which you want to retrieve payment methods. For the list of possible marketplace identifiers, refer to Marketplace IDs.

paymentMethodTypes
array of strings
length ≥ 1
A comma-separated list of the payment method types you want to include in the response.

Show Details
BANK_ACCOUNT	The payment is from a bank account.
CARD	The payment is from a card.
SELLER_WALLET	The payment is from a [Seller Wallet](https://sell.amazon.com/tools/seller-wallet) virtual bank account.
BANK_ACCOUNTCARDSELLER_WALLET
Responses

200
Success.

Response body
object
paymentMethods
array of objects
The list of payment methods with payment method details.

object
accountHolderName
string
The name of the account holder who is registered for the payment method.

paymentMethodId
string
The payment method identifier.

tail
string
The last three or four digits of the payment method.

expiryDate
object
The expiration date of the card used for payment. If the payment method is not card, the expiration date is null.


expiryDate object
countryCode
string
The two-letter country code in ISO 3166-1 alpha-2 format. For payment methods in the card category, the code is for the country where the card was issued. For payment methods in the bank account category, the code is for the country where the account is located.

paymentMethodType
string
enum
The type of payment method.

BANK_ACCOUNT CARD SELLER_WALLET

Show Details
BANK_ACCOUNT	The payment is from a bank account.
CARD	The payment is from a card.
SELLER_WALLET	The payment is from a [Seller Wallet](https://sell.amazon.com/tools/seller-wallet) virtual bank account.
assignmentType
string
enum
The default payment method type.

DEFAULT_DEPOSIT_METHOD

Show Details
DEFAULT_DEPOSIT_METHOD	The default deposit method.
Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

curl --request GET \
     --url 'https://sellingpartnerapi-na.amazon.com/finances/transfers/2024-06-01/paymentMethods?paymentMethodTypes=' \
     --header 'accept: application/json'


     {
  "paymentMethods": [
    {
      "accountHolderName": "John Doe",
      "paymentMethodId": "0h_TU_CUS_4058fe2a-da6b-4b82-8e48-b20ff2eb4f6d",
      "paymentMethodType": "BANK_ACCOUNT",
      "tail": "677",
      "assignmentType": "DEFAULT_DEPOSIT_METHOD"
    },
    {
      "countryCode": "US",
      "accountHolderName": "John Doe",
      "paymentMethodId": "0h_TU_CUS_4058fe2a-da6b-4b82-8e48-b20ff2eb4f6d",
      "paymentMethodType": "CARD",
      "expiryDate": {
        "month": "3",
        "year": "2029"
      },
      "tail": "677"
    }
  ]
}

listHandoverSlots
post
https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/timeSlot

Returns time slots available for Easy Ship orders to be scheduled based on the package weight and dimensions that the seller specifies.

This operation is available for scheduled and unscheduled orders based on marketplace support. See Get Time Slots in the Marketplace Support Table.

This operation can return time slots that have either pickup or drop-off handover methods - see Supported Handover Methods in the Marketplace Support Table.

Usage Plan:

Rate (requests per second)	Burst
1	5
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The table above indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may see higher rate and burst values than those shown here. For more information, see Usage Plans and Rate Limits in the Selling Partner API.

Body Params

Expand All
⬍
The request schema for the listHandoverSlots operation.

marketplaceId
string
required
length between 1 and 255
A string of up to 255 characters.

amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

packageDimensions
object
required
The dimensions of the scheduled package.


packageDimensions object
packageWeight
object
required
The weight of the scheduled package


packageWeight object
Responses

200
Success.

Response body
object
amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

timeSlots
array of objects
required
length between 1 and 500
A list of time slots.

object
slotId
string
required
length between 1 and 255
A string of up to 255 characters.

startTime
date-time
A datetime value in ISO 8601 format.

endTime
date-time
A datetime value in ISO 8601 format.

handoverMethod
string
enum
Identifies the method by which a seller will hand a package over to Amazon Logistics.

PICKUP DROPOFF

Show Details
PICKUP	An Amazon Logistics carrier will pickup the package(s) from the seller's pickup address.
DROPOFF	Seller will need to drop off the package(s) to a designated location.
Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/timeSlot"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

{
  "amazonOrderId": "string",
  "timeSlots": [
    {
      "slotId": "string",
      "startTime": "2026-04-21T13:52:46.360Z",
      "endTime": "2026-04-21T13:52:46.360Z",
      "handoverMethod": "PICKUP"
    }
  ]
}

getScheduledPackage
get
https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/package

Returns information about a package, including dimensions, weight, time slot information for handover, invoice and item information, and status.

Usage Plan:

Rate (requests per second)	Burst
1	5
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The table above indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may see higher rate and burst values than those shown here. For more information, see Usage Plans and Rate Limits in the Selling Partner API.

Query Params
amazonOrderId
string
required
length between 1 and 255
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

marketplaceId
string
required
length between 1 and 255
An identifier for the marketplace in which the seller is selling.

Responses

200
Success.

Response body
object
scheduledPackageId
object
required
Identifies the scheduled package to be updated.

amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

packageId
string
An Amazon-defined identifier for the scheduled package.

packageDimensions
object
required
The dimensions of the scheduled package.

length
float
≥ 0.01
The numerical value of the specified dimension.

width
float
≥ 0.01
The numerical value of the specified dimension.

height
float
≥ 0.01
The numerical value of the specified dimension.

unit
string
enum
The unit of measurement used to measure the length.

cm

Show Details
cm	Centimeters
identifier
string
length between 1 and 255
A string of up to 255 characters.

packageWeight
object
required
The weight of the scheduled package

value
float
≥ 11
The weight of the package.

unit
string
enum
The unit of measurement used to measure the weight.

grams g

Show Details
grams	grams
g	grams
packageItems
array of objects
length ≤ 500
A list of items contained in the package.

object
orderItemId
string
length ≤ 255
The Amazon-defined order item identifier.

orderItemSerialNumbers
array of objects
length ≤ 100
A list of serial numbers for the items associated with the OrderItemId value.

packageTimeSlot
object
required
A time window to hand over an Easy Ship package to Amazon Logistics.

slotId
string
required
length between 1 and 255
A string of up to 255 characters.

startTime
date-time
A datetime value in ISO 8601 format.

endTime
date-time
A datetime value in ISO 8601 format.

handoverMethod
string
enum
Identifies the method by which a seller will hand a package over to Amazon Logistics.

PICKUP DROPOFF

Show Details
PICKUP	An Amazon Logistics carrier will pickup the package(s) from the seller's pickup address.
DROPOFF	Seller will need to drop off the package(s) to a designated location.
packageIdentifier
string
Optional seller-created identifier that is printed on the shipping label to help the seller identify the package.

invoice
object
Invoice number and date.

invoiceNumber
string
required
length between 1 and 255
A string of up to 255 characters.

invoiceDate
date-time
A datetime value in ISO 8601 format.

packageStatus
string
enum
The status of the package.

ReadyForPickup PickedUp AtOriginFC AtDestinationFC Delivered Rejected Undeliverable ReturnedToSeller LostInTransit LabelCanceled DamagedInTransit OutForDelivery

Show Details
ReadyForPickup	The package is ready for pickup.
PickedUp	The package has been picked up.
AtOriginFC	The package is at its origin fulfillment center.
AtDestinationFC	The package is at its destination fulfillment center.
Delivered	The package has been delivered.
Rejected	The package has been rejected.
Undeliverable	The package is not deliverable.
ReturnedToSeller	The package has been returned to the seller.
LostInTransit	The package has been lost in transit.
LabelCanceled	The package's label has been canceled.
DamagedInTransit	The package has been damaged in transit.
OutForDelivery	The package is out for delivery.
trackingDetails
object
Representation of tracking metadata.

trackingId
string
length between 1 and 255
A string of up to 255 characters.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/package"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "scheduledPackageId": {
    "amazonOrderId": "string",
    "packageId": "string"
  },
  "packageDimensions": {
    "length": 0,
    "width": 0,
    "height": 0,
    "unit": "cm",
    "identifier": "string"
  },
  "packageWeight": {
    "value": 0,
    "unit": "grams"
  },
  "packageItems": [
    {
      "orderItemId": "string",
      "orderItemSerialNumbers": [
        "string"
      ]
    }
  ],
  "packageTimeSlot": {
    "slotId": "string",
    "startTime": "2026-04-21T13:52:46.360Z",
    "endTime": "2026-04-21T13:52:46.360Z",
    "handoverMethod": "PICKUP"
  },
  "packageIdentifier": "string",
  "invoice": {
    "invoiceNumber": "string",
    "invoiceDate": "2026-04-21T13:52:46.360Z"
  },
  "packageStatus": "ReadyForPickup",
  "trackingDetails": {
    "trackingId": "string"
  }
}

createScheduledPackage
post
https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/package

Schedules an Easy Ship order and returns the scheduled package information.

This operation does the following:

Specifies the time slot and handover method for the order to be scheduled for delivery.

Updates the Easy Ship order status.

Generates a shipping label and an invoice. Calling createScheduledPackage also generates a warranty document if you specify a SerialNumber value. To get these documents, see How to get invoice, shipping label, and warranty documents.

Shows the status of Easy Ship orders when you call the getOrders operation of the Selling Partner API for Orders and examine the EasyShipShipmentStatus property in the response body.

See the Shipping Label, Invoice, and Warranty columns in the Marketplace Support Table to see which documents are supported in each marketplace.

Usage Plan:

Rate (requests per second)	Burst
1	5
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The table above indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may see higher rate and burst values than those shown here. For more information, see Usage Plans and Rate Limits in the Selling Partner API.

Body Params

Expand All
⬍
The request schema for the createScheduledPackage operation.

amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

marketplaceId
string
required
length between 1 and 255
A string of up to 255 characters.

packageDetails
object
required
Package details. Includes packageItems, packageTimeSlot, and packageIdentifier.


packageDetails object
Responses

200
Success.

Response body
object
scheduledPackageId
object
required
Identifies the scheduled package to be updated.

amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

packageId
string
An Amazon-defined identifier for the scheduled package.

packageDimensions
object
required
The dimensions of the scheduled package.

length
float
≥ 0.01
The numerical value of the specified dimension.

width
float
≥ 0.01
The numerical value of the specified dimension.

height
float
≥ 0.01
The numerical value of the specified dimension.

unit
string
enum
The unit of measurement used to measure the length.

cm

Show Details
cm	Centimeters
identifier
string
length between 1 and 255
A string of up to 255 characters.

packageWeight
object
required
The weight of the scheduled package

value
float
≥ 11
The weight of the package.

unit
string
enum
The unit of measurement used to measure the weight.

grams g

Show Details
grams	grams
g	grams
packageItems
array of objects
length ≤ 500
A list of items contained in the package.

object
orderItemId
string
length ≤ 255
The Amazon-defined order item identifier.

orderItemSerialNumbers
array of objects
length ≤ 100
A list of serial numbers for the items associated with the OrderItemId value.

packageTimeSlot
object
required
A time window to hand over an Easy Ship package to Amazon Logistics.

slotId
string
required
length between 1 and 255
A string of up to 255 characters.

startTime
date-time
A datetime value in ISO 8601 format.

endTime
date-time
A datetime value in ISO 8601 format.

handoverMethod
string
enum
Identifies the method by which a seller will hand a package over to Amazon Logistics.

PICKUP DROPOFF

Show Details
PICKUP	An Amazon Logistics carrier will pickup the package(s) from the seller's pickup address.
DROPOFF	Seller will need to drop off the package(s) to a designated location.
packageIdentifier
string
Optional seller-created identifier that is printed on the shipping label to help the seller identify the package.

invoice
object
Invoice number and date.

invoiceNumber
string
required
length between 1 and 255
A string of up to 255 characters.

invoiceDate
date-time
A datetime value in ISO 8601 format.

packageStatus
string
enum
The status of the package.

ReadyForPickup PickedUp AtOriginFC AtDestinationFC Delivered Rejected Undeliverable ReturnedToSeller LostInTransit LabelCanceled DamagedInTransit OutForDelivery

Show Details
ReadyForPickup	The package is ready for pickup.
PickedUp	The package has been picked up.
AtOriginFC	The package is at its origin fulfillment center.
AtDestinationFC	The package is at its destination fulfillment center.
Delivered	The package has been delivered.
Rejected	The package has been rejected.
Undeliverable	The package is not deliverable.
ReturnedToSeller	The package has been returned to the seller.
LostInTransit	The package has been lost in transit.
LabelCanceled	The package's label has been canceled.
DamagedInTransit	The package has been damaged in transit.
OutForDelivery	The package is out for delivery.
trackingDetails
object
Representation of tracking metadata.

trackingId
string
length between 1 and 255
A string of up to 255 characters.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/package"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

{
  "scheduledPackageId": {
    "amazonOrderId": "string",
    "packageId": "string"
  },
  "packageDimensions": {
    "length": 0,
    "width": 0,
    "height": 0,
    "unit": "cm",
    "identifier": "string"
  },
  "packageWeight": {
    "value": 0,
    "unit": "grams"
  },
  "packageItems": [
    {
      "orderItemId": "string",
      "orderItemSerialNumbers": [
        "string"
      ]
    }
  ],
  "packageTimeSlot": {
    "slotId": "string",
    "startTime": "2026-04-21T13:52:46.360Z",
    "endTime": "2026-04-21T13:52:46.360Z",
    "handoverMethod": "PICKUP"
  },
  "packageIdentifier": "string",
  "invoice": {
    "invoiceNumber": "string",
    "invoiceDate": "2026-04-21T13:52:46.360Z"
  },
  "packageStatus": "ReadyForPickup",
  "trackingDetails": {
    "trackingId": "string"
  }
}

updateScheduledPackages
patch
https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/package

Updates the time slot for handing over the package indicated by the specified scheduledPackageId. You can get the new slotId value for the time slot by calling the listHandoverSlots operation before making another patch call.

See the Update Package column in the Marketplace Support Table to see which marketplaces this operation is supported in.

Usage Plan:

Rate (requests per second)	Burst
1	5
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The table above indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may see higher rate and burst values than those shown here. For more information, see Usage Plans and Rate Limits in the Selling Partner API.

Body Params

Expand All
⬍
The request schema for the updateScheduledPackages operation.

marketplaceId
string
required
length between 1 and 255
A string of up to 255 characters.

updatePackageDetailsList
array of objects
required
length between 1 and 500
A list of package update details.


object

scheduledPackageId
object
required
Identifies the scheduled package to be updated.


scheduledPackageId object
packageTimeSlot
object
required
A time window to hand over an Easy Ship package to Amazon Logistics.


packageTimeSlot object

ADD object
Responses

200
Success

Response body
object
packages
array of objects
required
length between 1 and 500
A list of packages.

object
scheduledPackageId
object
required
Identifies the scheduled package to be updated.


scheduledPackageId object
packageDimensions
object
required
The dimensions of the scheduled package.


packageDimensions object
packageWeight
object
required
The weight of the scheduled package


packageWeight object
packageItems
array of objects
length ≤ 500
A list of items contained in the package.

object
orderItemId
string
length ≤ 255
The Amazon-defined order item identifier.

orderItemSerialNumbers
array of objects
length ≤ 100
A list of serial numbers for the items associated with the OrderItemId value.

packageTimeSlot
object
required
A time window to hand over an Easy Ship package to Amazon Logistics.


packageTimeSlot object
packageIdentifier
string
Optional seller-created identifier that is printed on the shipping label to help the seller identify the package.

invoice
object
Invoice number and date.


invoice object
packageStatus
string
enum
The status of the package.

ReadyForPickup PickedUp AtOriginFC AtDestinationFC Delivered Rejected Undeliverable ReturnedToSeller LostInTransit LabelCanceled DamagedInTransit OutForDelivery

Show Details
ReadyForPickup	The package is ready for pickup.
PickedUp	The package has been picked up.
AtOriginFC	The package is at its origin fulfillment center.
AtDestinationFC	The package is at its destination fulfillment center.
Delivered	The package has been delivered.
Rejected	The package has been rejected.
Undeliverable	The package is not deliverable.
ReturnedToSeller	The package has been returned to the seller.
LostInTransit	The package has been lost in transit.
LabelCanceled	The package's label has been canceled.
DamagedInTransit	The package has been damaged in transit.
OutForDelivery	The package is out for delivery.
trackingDetails
object
Representation of tracking metadata.


trackingDetails object
Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/package"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.patch(url, headers=headers)

print(response.text)

{
  "packages": [
    {
      "scheduledPackageId": {
        "amazonOrderId": "string",
        "packageId": "string"
      },
      "packageDimensions": {
        "length": 0,
        "width": 0,
        "height": 0,
        "unit": "cm",
        "identifier": "string"
      },
      "packageWeight": {
        "value": 0,
        "unit": "grams"
      },
      "packageItems": [
        {
          "orderItemId": "string",
          "orderItemSerialNumbers": [
            "string"
          ]
        }
      ],
      "packageTimeSlot": {
        "slotId": "string",
        "startTime": "2026-04-21T13:52:46.360Z",
        "endTime": "2026-04-21T13:52:46.360Z",
        "handoverMethod": "PICKUP"
      },
      "packageIdentifier": "string",
      "invoice": {
        "invoiceNumber": "string",
        "invoiceDate": "2026-04-21T13:52:46.360Z"
      },
      "packageStatus": "ReadyForPickup",
      "trackingDetails": {
        "trackingId": "string"
      }
    }
  ]
}

createScheduledPackageBulk
post
https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/packages/bulk

This operation automatically schedules a time slot for all the amazonOrderIds given as input, generating the associated shipping labels, along with other compliance documents according to the marketplace (refer to the marketplace document support table).

Developers calling this operation may optionally assign a packageDetails object, allowing them to input a preferred time slot for each order in ther request. In this case, Amazon will try to schedule the respective packages using their optional settings. On the other hand, i.e., if the time slot is not provided, Amazon will then pick the earliest time slot possible.

Regarding the shipping label's file format, external developers are able to choose between PDF or ZPL, and Amazon will create the label accordingly.

This operation returns an array composed of the scheduled packages, and a short-lived URL pointing to a zip file containing the generated shipping labels and the other documents enabled for your marketplace. If at least an order couldn't be scheduled, then Amazon adds the rejectedOrders list into the response, which contains an entry for each order we couldn't process. Each entry is composed of an error message describing the reason of the failure, so that sellers can take action.

The table below displays the supported request and burst maximum rates:

Usage Plan:

Rate (requests per second)	Burst
1	5
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The table above indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may see higher rate and burst values than those shown here. For more information, see Usage Plans and Rate Limits in the Selling Partner API.

Body Params

Expand All
⬍
The request schema for the createScheduledPackageBulk operation.

marketplaceId
string
required
length between 1 and 255
A string of up to 255 characters.

orderScheduleDetailsList
array of objects
required
length ≥ 1
An array allowing users to specify orders to be scheduled.


object

amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

packageDetails
object
Package details. Includes packageItems, packageTimeSlot, and packageIdentifier.


packageDetails object

ADD object
labelFormat
string
enum
required
The file format in which the shipping label will be created.


PDF
Allowed:

PDF

ZPL
Responses

200
Success

Response body
object
scheduledPackages
array of objects
length ≤ 100
A list of packages. Refer to the Package object.

object
scheduledPackageId
object
required
Identifies the scheduled package to be updated.


scheduledPackageId object
packageDimensions
object
required
The dimensions of the scheduled package.


packageDimensions object
packageWeight
object
required
The weight of the scheduled package


packageWeight object
packageItems
array of objects
length ≤ 500
A list of items contained in the package.

object
orderItemId
string
length ≤ 255
The Amazon-defined order item identifier.

orderItemSerialNumbers
array of objects
length ≤ 100
A list of serial numbers for the items associated with the OrderItemId value.

packageTimeSlot
object
required
A time window to hand over an Easy Ship package to Amazon Logistics.


packageTimeSlot object
packageIdentifier
string
Optional seller-created identifier that is printed on the shipping label to help the seller identify the package.

invoice
object
Invoice number and date.


invoice object
packageStatus
string
enum
The status of the package.

ReadyForPickup PickedUp AtOriginFC AtDestinationFC Delivered Rejected Undeliverable ReturnedToSeller LostInTransit LabelCanceled DamagedInTransit OutForDelivery

Show Details
ReadyForPickup	The package is ready for pickup.
PickedUp	The package has been picked up.
AtOriginFC	The package is at its origin fulfillment center.
AtDestinationFC	The package is at its destination fulfillment center.
Delivered	The package has been delivered.
Rejected	The package has been rejected.
Undeliverable	The package is not deliverable.
ReturnedToSeller	The package has been returned to the seller.
LostInTransit	The package has been lost in transit.
LabelCanceled	The package's label has been canceled.
DamagedInTransit	The package has been damaged in transit.
OutForDelivery	The package is out for delivery.
trackingDetails
object
Representation of tracking metadata.


trackingDetails object
rejectedOrders
array of objects
A list of orders we couldn't scheduled on your behalf. Each element contains the reason and details on the error.

object
amazonOrderId
string
required
An Amazon-defined order identifier. Identifies the order that the seller wants to deliver using Amazon Easy Ship.

error
object
Error response returned when the request is unsuccessful.


error object
printableDocumentsUrl
string
A pre-signed URL for the zip document containing the shipping labels and the documents enabled for your marketplace.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/easyShip/2022-03-23/packages/bulk"

payload = { "labelFormat": "PDF" }
headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)

{
  "scheduledPackages": [
    {
      "scheduledPackageId": {
        "amazonOrderId": "string",
        "packageId": "string"
      },
      "packageDimensions": {
        "length": 0,
        "width": 0,
        "height": 0,
        "unit": "cm",
        "identifier": "string"
      },
      "packageWeight": {
        "value": 0,
        "unit": "grams"
      },
      "packageItems": [
        {
          "orderItemId": "string",
          "orderItemSerialNumbers": [
            "string"
          ]
        }
      ],
      "packageTimeSlot": {
        "slotId": "string",
        "startTime": "2026-04-21T13:52:46.360Z",
        "endTime": "2026-04-21T13:52:46.360Z",
        "handoverMethod": "PICKUP"
      },
      "packageIdentifier": "string",
      "invoice": {
        "invoiceNumber": "string",
        "invoiceDate": "2026-04-21T13:52:46.360Z"
      },
      "packageStatus": "ReadyForPickup",
      "trackingDetails": {
        "trackingId": "string"
      }
    }
  ],
  "rejectedOrders": [
    {
      "amazonOrderId": "string",
      "error": {
        "code": "string",
        "message": "string",
        "details": "string"
      }
    }
  ],
  "printableDocumentsUrl": "string"
}


getMarketplaceParticipations
get
https://sellingpartnerapi-na.amazon.com/sellers/v1/marketplaceParticipations

Returns a list of marketplaces where the seller can list items and information about the seller's participation in those marketplaces.

Usage Plan:

Rate (requests per second)	Burst
0.016	15
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the Selling Partner API.

Headers
accept
string
enum
Defaults to application/json
Generated from available response content types


application/json
Allowed:

application/json

payload
Responses

200
Marketplace participations successfully retrieved.

Response body

application/json
object
payload
array of objects
List of marketplace participations.

object
marketplace
object
required
Information about an Amazon marketplace where a seller can list items and customers can view and purchase items.


marketplace object
participation
object
required
Information that is specific to a seller in a marketplace.


participation object
storeName
string
required
The name of the seller's store as displayed in the marketplace.

errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help you understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/sellers/v1/marketplaceParticipations"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

{
  "payload": [
    {
      "marketplace": {
        "id": "string",
        "name": "string",
        "countryCode": "string",
        "defaultCurrencyCode": "string",
        "defaultLanguageCode": "string",
        "domainName": "string"
      },
      "participation": {
        "isParticipating": true,
        "hasSuspendedListings": true
      },
      "storeName": "string"
    }
  ],
  "errors": [
    {
      "code": "string",
      "message": "string",
      "details": "string"
    }
  ]
}



getAccount
get
https://sellingpartnerapi-na.amazon.com/sellers/v1/account

Returns information about a seller account and its marketplaces.

Usage Plan:

Rate (requests per second)	Burst
0.016	15
The x-amzn-RateLimit-Limit response header returns the usage plan rate limits that were applied to the requested operation, when available. The preceding table indicates the default rate and burst values for this operation. Selling partners whose business demands require higher throughput may have higher rate and burst values than those shown here. For more information, refer to Usage Plans and Rate Limits in the Selling Partner API.

Responses

200
Success.

Response body
object
payload
object
The response schema for the getAccount operation.

marketplaceParticipationList
array of objects
required
List of marketplace participations.

object
marketplace
object
required
Information about an Amazon marketplace where a seller can list items and customers can view and purchase items.


marketplace object
participation
object
required
Information that is specific to a seller in a marketplace.


participation object
storeName
string
required
The name of the seller's store as displayed in the marketplace.

businessType
string
enum
required
The type of business registered for the seller account.

CHARITY CRAFTSMAN NATURAL_PERSON_COMPANY PUBLIC_LISTED PRIVATE_LIMITED SOLE_PROPRIETORSHIP STATE_OWNED INDIVIDUAL

Show Details
CHARITY	The business is registered as a charity.
CRAFTSMAN	The business is registered as a craftsman.
NATURAL_PERSON_COMPANY	The business is a natural person company.
PUBLIC_LISTED	The business is a publicly listed company.
PRIVATE_LIMITED	The business is a private limited company.
SOLE_PROPRIETORSHIP	The business is a sole proprietorship.
STATE_OWNED	The business is state-owned.
INDIVIDUAL	The entity is not a business but an individual.
sellingPlan
string
enum
required
The selling plan details.

PROFESSIONAL INDIVIDUAL

Show Details
PROFESSIONAL	The seller has a professional selling plan.
INDIVIDUAL	The seller has an individual selling plan.
business
object
Information about the seller's business. Certain fields may be omitted depending on the seller's businessType.


business object
primaryContact
object
Information about the seller's primary contact.


primaryContact object
errors
array of objects
A list of error responses returned when a request is unsuccessful.

object
code
string
required
An error code that identifies the type of error that occurred.

message
string
required
A message that describes the error condition in a human-readable form.

details
string
Additional details that can help you understand or fix the issue.

Headers
object
x-amzn-RateLimit-Limit
string
Your rate limit (requests per second) for this operation.

x-amzn-RequestId
string
Unique request reference identifier.

import requests

url = "https://sellingpartnerapi-na.amazon.com/sellers/v1/account"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


{
  "payload": {
    "businessType": "PRIVATE_LIMITED",
    "marketplaceParticipationList": [
      {
        "marketplace": {
          "id": "ATVPDKIKX0DER",
          "name": "United States",
          "countryCode": "US",
          "domainName": "www.amazon.com"
        },
        "storeName": "BestSellerStore",
        "participation": {
          "isParticipating": true,
          "hasSuspendedListings": false
        }
      }
    ],
    "sellingPlan": "PROFESSIONAL",
    "business": {
      "name": "BestSeller Inc.",
      "nonLatinName": "ベストセラー株式会社",
      "registeredBusinessAddress": {
        "addressLine1": "123 Main St",
        "addressLine2": "Suite 500",
        "city": "Seattle",
        "stateOrProvinceCode": "WA",
        "postalCode": "98101",
        "countryCode": "US"
      },
      "companyRegistrationNumber": "123456789",
      "companyTaxIdentificationNumber": "987654321"
    },
    "primaryContact": {
      "name": "John Doe",
      "nonLatinName": "ジョン・ドゥ",
      "address": {
        "addressLine1": "456 Oak St",
        "addressLine2": "Apt 12",
        "city": "Seattle",
        "stateOrProvinceCode": "WA",
        "postalCode": "98102",
        "countryCode": "US"
      }
    }
  }
}