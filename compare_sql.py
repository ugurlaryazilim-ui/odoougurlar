#!/usr/bin/env python3
"""Hamurlabs vs Odoo SQL verisi karşılaştırma."""
import json, sys

sys.stdout.reconfigure(encoding='utf-8')

def parse(path):
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

def compare(title, file_h, file_o, fields):
    print('=' * 90)
    print(title)
    print('=' * 90)
    h = parse(file_h)
    o = parse(file_o)
    header = f"{'Alan':30s} {'Hamurlabs':25s} {'Odoo':25s} {'Durum'}"
    print(header)
    print('-' * 90)
    for field in fields:
        h_val = h.get(field, 'N/A')
        o_val = o.get(field, 'N/A')
        match = 'OK' if str(h_val) == str(o_val) else '*** FARKLI ***'
        print(f"{field:30s} {str(h_val):25s} {str(o_val):25s} {match}")
    print()

# CARI
compare(
    'CARI KARSILASTIRMA (SQL)',
    'Curr_hamurlabs.json', 'Curr_odoo.json',
    ['IsIndividualAcc', 'IsSubjectToEInvoice', 'IsSubjectToEShipment',
     'FirstName', 'LastName', 'IdentityNum', 'TaxNumber', 'TaxOfficeCode',
     'CurrencyCode', 'CustomerTypeCode', 'IsArrangeCommercialInvoice',
     'CurrAccTypeCode']
)

# SIPARIS
compare(
    'SIPARIS KARSILASTIRMA (SQL)',
    'order_hamurlabs.json', 'order_odoo.json',
    ['ShipmentMethodCode', 'TaxExemptionCode', 'TaxTypeCode',
     'WarehouseCode', 'StoreCode', 'POSTerminalID', 'OfficeCode',
     'DeliveryCompanyCode', 'IsCompleted', 'IsSalesViaInternet',
     'IsCreditableConfirmed', 'IsOrderBase' if False else 'OrderTypeCode']
)

# FATURA
compare(
    'FATURA KARSILASTIRMA (SQL)',
    'invoice_hamurlabs.json', 'invoice_odoo.json',
    ['InvoiceTypeCode', 'IsEInvoice', 'EInvoiceNumber', 'EInvoiceStatusCode',
     'IsPostingJournal', 'IsCompleted', 'IsOrderBase', 'IsShipmentBase',
     'IsDelivered', 'IsSalesViaInternet', 'SendInvoiceByEMail',
     'ShipmentMethodCode', 'TaxExemptionCode', 'DocumentTypeCode',
     'StoreCode', 'WarehouseCode', 'POSTerminalID',
     'DeliveryCompanyCode', 'FiscalPrintedState', 'FormType',
     'InvoiceGiftCard', 'IsProposalBased', 'IsSuspended', 'IsLocked',
     'IsPrinted', 'IsProforma', 'IsCreditSale']
)
