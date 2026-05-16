import json, sys, re

sys.stdout.reconfigure(encoding='utf-8')

def load(path):
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    # SSMS adds \r\n inside long strings and numbers
    # This can break JSON like "0.\r\n0000" -> "0. 0000"
    # Fix: remove ALL whitespace inside numbers that got split
    text = text.replace('\r\n', '').replace('\r', '').replace('\n', '')
    # Fix broken numbers: "0. 0000" -> "0.0000"
    text = re.sub(r'(\d+)\.\s+(\d+)', r'\1.\2', text)
    # Remove trailing non-JSON
    last = text.rfind('}')
    if last > 0:
        text = text[:last+1]
    return json.loads(text)

inv_h = load('invoice_hamurlabs.json')
inv_o = load('invoice_odoo.json')

skip_prefixes = ('Doc_', 'Loc_', 'Com_', 'Created', 'LastUpdated', 'RowGuid')
skip_exact = {'InvoiceHeaderID','InvoiceLineID','ApplicationID','OrderLineID',
              'InvoiceNumber','InvoiceDate','InvoiceTime','OperationDate','OperationTime',
              'JournalDate','AverageDueDate','Price','ItemCode','ColorCode','ItemDim1Code',
              'UsedBarcode','CurrAccCode','BillingPostalAddressID','ShippingPostalAddressID',
              'EMailAddress','SortOrder'}

print('FATURA FARKLARI (anlamli)')
print('=' * 100)
all_keys = sorted(set(list(inv_h.keys()) + list(inv_o.keys())))
for k in all_keys:
    if any(k.startswith(p) for p in skip_prefixes): continue
    if k in skip_exact: continue
    hv = inv_h.get(k, '<<YOK>>')
    ov = inv_o.get(k, '<<YOK>>')
    if hv != ov:
        print('  %-40s | H: %-30s | O: %-30s' % (k, str(hv)[:30], str(ov)[:30]))

print()
print('KONTROL ALANLARI:')
important = ['InvoiceTypeCode','IsEInvoice','EInvoiceNumber','EInvoiceStatusCode','EInvoiceAliasCode',
             'IsPostingJournal','SendInvoiceByEMail','IsCompleted','IsOrderBase',
             'IsSalesViaInternet','ShipmentMethodCode','DeliveryCompanyCode',
             'Description','InternalDescription','DocumentTypeCode','FormType',
             'StoreTypeCode','StoreCode','WarehouseCode','POSTerminalID',
             'TaxTypeCode','TaxExemptionCode','IsInclutedVat','IsDelivered',
             'FiscalPrintedState','ExpenseTypeCode','TransTypeCode','ProcessCode']
for k in important:
    hv = inv_h.get(k, '<<YOK>>')
    ov = inv_o.get(k, '<<YOK>>')
    marker = 'FARK!' if hv != ov else '     '
    print('%s %-40s | H: %-30s | O: %-30s' % (marker, k, str(hv)[:30], str(ov)[:30]))
