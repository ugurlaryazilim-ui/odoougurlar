#!/usr/bin/env python3
"""Hamurlabs vs Odoo fatura istek karşılaştırması."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

# Hamurlabs fatura isteği (daha önceki konuşmadan)
hamurlabs_request = {
    "IsCompleted": True,
    "OrdersViaInternetInfo": {
        "PaymentTypeDescription": "KREDIKARTI/BANKAKARTI",
        "SendDate": "2026-04-24",
        "PaymentDate": "2026-04-23",
        "SalesURL": "www.trendyol.com",
        "PaymentTypeCode": 1,
        "PaymentAgent": ""
    },
    "POSTerminalID": "1",
    "BillingPostalAddressID": "bbb223a6-966c-4beb-aa79-b4360065b79c",
    "Lines": [{
        "Qty1": 1.0,
        "SalesPersonCode": "TRD",
        "UsedBarcode": "5715507626053",
        "PriceVI": 864.35
    }],
    "OfficeCode": "M",
    "DocumentNumber": "3789826504_11166717429",
    "Payments": [{
        "CreditCardTypeCode": "TRD",
        "Code": "",
        "InstallmentCount": 1,
        "DocumentDate": "\\/Date(1776937215)\\/",
        "PaymentType": "2",
        "Amount": 864.35,
        "CurrencyCode": "TRY"
    }],
    "IsSalesViaInternet": True,
    "ShipmentMethodCode": "2",
    "StoreCode": "002",
    "WarehouseCode": "002",
    "InternalDescription": "3789826504_11166717429",
    "CustomerCode": "1-4-166176",
    "IsOrderBase": False,
    "ModelType": 8
}

# Odoo fatura isteği (son gönderilen)
odoo_request = {
    "ModelType": 8,
    "CustomerCode": "1-4-167322",
    "Description": "11235599315",
    "InternalDescription": "11235599315",
    "InvoiceDate": "20260517",
    "OfficeCode": "M",
    "StoreCode": "002",
    "WarehouseCode": "002",
    "POSTerminalID": 1,
    "ShipmentMethodCode": "2",
    "DeliveryCompanyCode": "YRT",
    "IsOrderBase": True,
    "IsSalesViaInternet": True,
    "IsCompleted": True,
    "IsPostingJournal": True,
    "SendInvoiceByEMail": True,
    "EMailAddress": "pf+6lv8v28x@trendyolmail.com",
    "Lines": [{
        "Qty1": 1.0,
        "OrderLineID": "6ed85cbd-3c68-4f8f-80ef-b44d00db81ef"
    }],
    "Payments": [{
        "PaymentType": "2",
        "Code": "",
        "CreditCardTypeCode": "TRD",
        "InstallmentCount": 1,
        "CurrencyCode": "TRY",
        "AmountVI": 6515.0,
        "BankCode": "102.011.002"
    }],
    "SalesViaInternetInfo": {
        "SalesURL": "www.trendyol.com",
        "PaymentTypeCode": 1,
        "PaymentTypeDescription": "KREDIKARTI/BANKAKARTI",
        "PaymentDate": "2026-05-17 13:19:08",
        "SendDate": "2026-05-17 13:21:03",
        "PaymentAgent": "TrendyolMp"
    },
    "BillingPostalAddressID": "1cc2a334-aff4-4a5e-bbf6-b44d00db80d6",
    "ShippingPostalAddressID": "1cc2a334-aff4-4a5e-bbf6-b44d00db80d6",
    "PostalAddress": {
        "FirstName": "şükrü",
        "LastName": "ulaş saraç lovefengis",
        "IdentityNum": "59239421308"
    }
}

# Karşılaştır
print("=" * 90)
print("FATURA İSTEK KARSILASTIRMASI (API JSON)")
print("=" * 90)

# Hamurlabs'ta VAR ama Odoo'da YOK
h_keys = set(hamurlabs_request.keys())
o_keys = set(odoo_request.keys())

print("\n--- Hamurlabs'ta VAR, Odoo'da YOK ---")
for k in sorted(h_keys - o_keys):
    print(f"  {k}: {hamurlabs_request[k]}")

print("\n--- Odoo'da VAR, Hamurlabs'ta YOK ---")
for k in sorted(o_keys - h_keys):
    val = odoo_request[k]
    if isinstance(val, dict):
        print(f"  {k}: {json.dumps(val, ensure_ascii=False)}")
    else:
        print(f"  {k}: {val}")

print("\n--- Her İkisinde VAR ama FARKLI ---")
for k in sorted(h_keys & o_keys):
    h_val = hamurlabs_request[k]
    o_val = odoo_request[k]
    if str(h_val) != str(o_val):
        if isinstance(h_val, dict) or isinstance(o_val, dict):
            print(f"\n  {k}:")
            print(f"    Hamurlabs: {json.dumps(h_val, ensure_ascii=False)}")
            print(f"    Odoo:      {json.dumps(o_val, ensure_ascii=False)}")
        else:
            print(f"  {k}: Hamurlabs={h_val}, Odoo={o_val}")
