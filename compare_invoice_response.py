#!/usr/bin/env python3
"""Fatura yanıtı karşılaştırma: Hamurlabs e-arşiv GEÇEN vs Odoo GEÇMEYEN."""
import json, sys
sys.stdout.reconfigure(encoding='utf-8')

# Odoo fatura YANITI'ndan kritik alanlar
odoo_invoice_response = {
    'EArchivePrefixCode': 'UGE',
    'EInvoiceAliasCode': '',
    'EInvoiceNumber': 'None',
    'EInvoiceStatusCode': 0,
    'ShouldPrintEArchiveOnSave': True,
    'IsPostingJournal': '?? (yanıtta yok)',
    'PostalAddress.FirstName': 'şükrü',
    'PostalAddress.LastName': 'ulaş saraç lovefengis',
    'PostalAddress.IdentityNum': '59239421308',
    'PostalAddress.TaxNumber': '',
    'PostalAddress.CompanyName': '',
    'InvoiceHeaderExtension.IsIndividual': False,  # ÇOK ÖNEMLİ!
}

# Odoo fatura İSTEĞİ'nden kritik farklar
odoo_invoice_request_extras = {
    'PostalAddress': 'GÖNDERİLDİ → {FirstName, LastName, IdentityNum}',
    'IsPostingJournal': True,
    'SendInvoiceByEMail': True,
    'EMailAddress': 'pf+6lv8v28x@trendyolmail.com',
    'SalesViaInternetInfo_key': 'SalesViaInternetInfo (Hamurlabs: OrdersViaInternetInfo)',
    'IsOrderBase': True,
    'Lines': 'OrderLineID ile (sipariş bazlı)',
}

hamurlabs_invoice_request_extras = {
    'PostalAddress': 'GÖNDERİLMEDİ ❌',
    'IsPostingJournal': 'GÖNDERİLMEDİ',
    'SendInvoiceByEMail': 'GÖNDERİLMEDİ',
    'EMailAddress': 'GÖNDERİLMEDİ',
    'Internet_key': 'OrdersViaInternetInfo',
    'IsOrderBase': False,
    'Lines': 'PriceVI + UsedBarcode ile (serbest fatura)',
}

print("=" * 110)
print("FATURA İSTEK → HAMURLABS (E-ARŞİV GEÇEN) vs ODOO (NONE/10013)")
print("=" * 110)

print(f"\n{'Alan':45s} {'Hamurlabs':30s} {'Odoo':30s}")
print("-" * 110)

compare_fields = [
    ('PostalAddress', 'GÖNDERİLMEDİ ❌', 'FirstName+LastName+IdentityNum'),
    ('IsPostingJournal', 'GÖNDERİLMEDİ', 'true'),
    ('SendInvoiceByEMail', 'GÖNDERİLMEDİ', 'true'),
    ('EMailAddress', 'GÖNDERİLMEDİ', 'pf+6lv...@trendyolmail.com'),
    ('IsOrderBase', 'False (serbest)', 'True (sipariş bazlı)'),
    ('Lines yapısı', 'PriceVI+UsedBarcode', 'OrderLineID'),
    ('Internet key adı', 'OrdersViaInternetInfo', 'SalesViaInternetInfo'),
]

for field, h_val, o_val in compare_fields:
    mark = '*** FARKLI ***' if h_val != o_val else 'AYNI'
    print(f"  {field:43s} {h_val:30s} {o_val:30s} {mark}")

print("\n" + "=" * 110)
print("FATURA YANITI → KRİTİK E-FATURA ALANLARI")
print("=" * 110)

print(f"\n{'Alan':45s} {'Odoo Yanıt':30s} {'Sorun?'}")
print("-" * 110)

critical = [
    ('EInvoiceNumber', 'None', '⚠️ FATURA NO ALANAMADI'),
    ('EInvoiceStatusCode', '0', '⚠️ İŞLENMEDİ (12 olmalı)'),
    ('EArchivePrefixCode', 'UGE', '✅ E-Arşiv prefiksi doğru'),
    ('EInvoiceAliasCode', '(boş)', '❓ E-fatura alias yok'),
    ('ShouldPrintEArchiveOnSave', 'True', '✅ E-arşiv olarak yazdırılacak'),
    ('PostalAddress.FirstName', 'şükrü', '🔴 BİZ GÖNDERDİK → Sematron GİB kontrol'),
    ('PostalAddress.IdentityNum', '59239421308', '🔴 BİZ GÖNDERDİK → GİB sorgusu'),
    ('InvoiceHeaderExtension.IsIndividual', 'False', '🔴 FALSE! Gerçek kişi DEĞİL gibi!'),
]

for field, val, status in critical:
    print(f"  {field:43s} {val:30s} {status}")

print("\n" + "=" * 110)
print("POSTAL ADDRESS KARŞILAŞTIRMA (prCurrAccPostalAddress SQL)")
print("=" * 110)

print(f"\n{'Alan':30s} {'Hamurlabs':35s} {'Odoo':35s}")
print("-" * 110)

addr_compare = [
    ('AddressTypeCode', '2 (Teslimat)', '1 (Fatura)'),
    ('CountryCode', 'TR', 'TR'),
    ('StateCode', 'TR.EG', 'TR.EG'),
    ('CityCode', 'TR.48 (Muğla)', 'TR.35 (İzmir)'),
    ('DistrictCode', 'TR.04803', 'TR.03500'),
    ('ZipCode', '48000', '(boş)'),
    ('TaxOfficeCode', '(boş)', '(boş)'),
    ('TaxNumber', '(boş)', '(boş)'),
]

for field, h, o in addr_compare:
    mark = '' if h == o else '*** FARKLI ***'
    print(f"  {field:28s} {h:35s} {o:35s} {mark}")

print("\n" + "=" * 110)
print("🔴 SONUÇ ANALİZİ")
print("=" * 110)
print("""
İki TC de GİB'de e-fatura mükellefi → Hamurlabs geçmiş, biz geçmemişiz.

BULGUlar:
1. PostalAddress BLOĞU → Hamurlabs faturada GÖNDERMEMİŞ, biz gönderiyoruz
   → IdentityNum ile Sematron GİB kontrolü yapıyor → 10013

2. InvoiceHeaderExtension.IsIndividual = False → Nebim bu kişiyi 
   TÜZEL KİŞİ gibi işliyor! Şahıs olarak değil.
   → Bu yüzden GİB'den e-fatura kontrolü yapılıyor olabilir.

3. AddressTypeCode: Hamurlabs "2", Odoo "1"
   → Fatura adresi (1) vs Teslimat adresi (2) farkı

ÇÖZÜM ÖNERİSİ:
→ PostalAddress bloğunu fatura isteğinden KALDIR
→ Nebim zaten cari'den kimlik bilgisini biliyor
→ Hamurlabs hiç göndermemiş ve çalışmış
""")
