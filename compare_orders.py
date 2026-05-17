#!/usr/bin/env python3
"""Sipariş karşılaştırma: SQL + API istekleri."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

def parse_sql(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        raw = f.read()
    lines = raw.strip().split('\n')
    json_text = ''
    for line in lines:
        line = line.strip()
        if line.startswith('{'):
            json_text += line
        elif json_text and not line.startswith('('):
            json_text += line
    last = json_text.rfind('}')
    if last > 0:
        json_text = json_text[:last+1]
    return json.loads(json_text)

# ═══ SQL SİPARİŞ KARŞILAŞTIRMA ═══
print("=" * 100)
print("SQL SİPARİŞ KARŞILAŞTIRMA (Nebim DB'de kaydolan son hali)")
print("=" * 100)

h_sql = parse_sql('order_hamurlabs.json')
o_sql = parse_sql('order_odoo.json')

# Tüm key'leri topla
all_keys = sorted(set(list(h_sql.keys()) + list(o_sql.keys())))
diffs = []
for k in all_keys:
    h = h_sql.get(k, '<<YOK>>')
    o = o_sql.get(k, '<<YOK>>')
    if str(h) != str(o):
        # Farklı müşteri/tarih/numara gibi doğal farkları atla
        if k in ('OrderHeaderID','OrderNumber','OrderDate','OrderTime','DocumentNumber',
                 'Description','InternalDescription','CurrAccCode','AverageDueDate',
                 'ShippingPostalAddressID','BillingPostalAddressID','ApplicationID',
                 'CreatedDate','LastUpdatedDate','CreditableConfirmedDate','DeliveryCompanyCode'):
            continue
        diffs.append((k, h, o))

print(f"\n{'Alan':35s} {'Hamurlabs':30s} {'Odoo':30s}")
print("-" * 100)
if diffs:
    for k, h, o in diffs:
        print(f"{k:35s} {str(h):30s} {str(o):30s}")
else:
    print("  Yapısal fark yok (sadece müşteri/tarih/numara farklılıkları)")

# ═══ API SİPARİŞ İSTEK KARŞILAŞTIRMA ═══
print("\n" + "=" * 100)
print("API SİPARİŞ İSTEK KARŞILAŞTIRMA (Nebim'e gönderdiğimiz JSON)")
print("=" * 100)

h_api = {
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
    "Lines": [{"Qty1": 1.0, "SalesPersonCode": "TRD", "UsedBarcode": "5715507626053", "PriceVI": 864.35}],
    "OfficeCode": "M",
    "DocumentNumber": "3789826504_11166717429",
    "Payments": [{"CreditCardTypeCode": "TRD", "Code": "", "InstallmentCount": 1,
                  "DocumentDate": "\\/Date(1776937215)\\/", "PaymentType": "2", "Amount": 864.35, "CurrencyCode": "TRY"}],
    "IsSalesViaInternet": True,
    "ShipmentMethodCode": "2",
    "StoreCode": "002",
    "WarehouseCode": "002",
    "InternalDescription": "3789826504_11166717429",
    "Description": "3789826504_11166717429",
    "DeliveryCompanyCode": "KLY",
    "ModelType": 6,
    "OrderDate": "2026-04-23",
    "CustomerCode": "1-4-166176",
    "ShippingPostalAddressID": "bbb223a6-966c-4beb-aa79-b4360065b79c"
}

o_api = {
    "ModelType": 6,
    "IsCompleted": True,
    "IsSalesViaInternet": True,
    "CustomerCode": "1-4-167334",
    "OfficeCode": "M",
    "StoreCode": "002",
    "WarehouseCode": "002",
    "ExportFileNumber": "",
    "ShipmentMethodCode": "2",
    "DocumentNumber": "11235599315",
    "Description": "11235599315",
    "InternalDescription": "S00342",
    "OrderDate": "2026-05-17",
    "DeliveryCompanyCode": "YRT",
    "BillingPostalAddressID": "ed06d7e4-8817-484c-84c7-b44d00f050e3",
    "ShippingPostalAddressID": "ed06d7e4-8817-484c-84c7-b44d00f050e3",
    "Lines": [{"Qty1": 1.0, "Price": 5922.727272727272, "UsedBarcode": "9296916988285", "SalesPersonCode": "TRD"}],
    "OrdersViaInternetInfo": {
        "SalesURL": "www.trendyol.com", "PaymentTypeCode": 1,
        "PaymentTypeDescription": "KREDIKARTI/BANKAKARTI",
        "SendDate": "2026-05-17", "PaymentDate": "2026-05-17",
        "PaymentAgent": "TrendyolMp"
    },
    "POSTerminalID": "1",
    "StoreWareHouseCode": "002",
    "Payments": [{"PaymentType": "2", "Code": "", "CreditCardTypeCode": "TRD",
                  "InstallmentCount": 1, "CurrencyCode": "TRY", "Amount": 6515.0, "BankCode": "102.011.002"}]
}

# Hamurlabs'ta VAR, Odoo'da YOK
skip_keys = {'CustomerCode','DocumentNumber','Description','InternalDescription','OrderDate',
             'BillingPostalAddressID','ShippingPostalAddressID','DeliveryCompanyCode'}
h_keys = set(h_api.keys()) - skip_keys
o_keys = set(o_api.keys()) - skip_keys

only_h = h_keys - o_keys
only_o = o_keys - h_keys
both = h_keys & o_keys

if only_o:
    print("\n--- Odoo'da VAR, Hamurlabs'ta YOK (FAZLA gönderdiğimiz) ---")
    for k in sorted(only_o):
        v = o_api[k]
        if isinstance(v, (dict, list)):
            print(f"  ⚠️  {k}: {json.dumps(v, ensure_ascii=False)}")
        else:
            print(f"  ⚠️  {k}: {v}")

if only_h:
    print("\n--- Hamurlabs'ta VAR, Odoo'da YOK (EKSİK gönderdiğimiz) ---")
    for k in sorted(only_h):
        v = h_api[k]
        print(f"  ❌ {k}: {v}")

print("\n--- Her İkisinde VAR ama FARKLI ---")
for k in sorted(both):
    h_v = h_api[k]
    o_v = o_api[k]
    if str(h_v) != str(o_v):
        if isinstance(h_v, (dict, list)):
            print(f"\n  🔍 {k}:")
            print(f"     Hamurlabs: {json.dumps(h_v, ensure_ascii=False)}")
            print(f"     Odoo:      {json.dumps(o_v, ensure_ascii=False)}")
        else:
            print(f"  🔍 {k}: Hamurlabs={h_v}, Odoo={o_v}")

# ═══ SIPARIS YANIT KARŞILAŞTIRMA ═══
print("\n" + "=" * 100)
print("SİPARİŞ YANITINDA KRİTİK FARKLAR")
print("=" * 100)

# Hamurlabs yanıtından önemli alanlar
print("\nHamurlabs yanıt (sipariş):")
print("  StoreWarehouseCode: '' (boş)")
print("  PaymentAgent: '' (boş)")
print("  Lines.PriceVI: 864.35 (KDV dahil)")
print("  Payments.Amount: 864.35 (DocumentDate ile)")

print("\nOdoo yanıt (sipariş):")
print("  StoreWarehouseCode: '002'")
print("  PaymentAgent: 'TrendyolMp'")
print("  Lines.Price: 5922.7273 (KDV hariç)")
print("  Payments.Amount ile BankCode gönderildi")
