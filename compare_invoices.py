import json, sys, re

sys.stdout.reconfigure(encoding='utf-8')

def load(path):
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ['utf-8', 'utf-16', 'utf-16-le', 'latin-1']:
        try:
            text = raw.decode(enc).strip()
            if '(1 rows affected)' in text:
                text = text.split('(1 rows affected)')[0].strip()
            text = text.replace('\r\n', '').replace('\r', '').replace('\n', '')
            text = re.sub(r'(\d+)\.\s+(\d+)', r'\1.\2', text)
            last = text.rfind('}')
            if last > 0:
                text = text[:last+1]
            j = json.loads(text)
            if isinstance(j, list):
                j = j[0]
            return j
        except:
            continue
    return None

# ═══════════════════════════════════════════════════════
# CARI
# ═══════════════════════════════════════════════════════
curr_h = load('Curr_hamurlabs.json')
curr_o = load('Curr_odoo.json')

skip_curr = {'CurrAccCode','CreatedUserName','CreatedDate','LastUpdatedUserName',
             'LastUpdatedDate','RowGuid','FirstLastName','FullName'}

print('=' * 110)
print('CARI KARSILASTIRMA')
print('=' * 110)

if curr_h and curr_o:
    all_keys = sorted(set(list(curr_h.keys()) + list(curr_o.keys())))
    
    print('\nFARKLAR:')
    for k in all_keys:
        if k in skip_curr: continue
        hv = curr_h.get(k, '<<YOK>>')
        ov = curr_o.get(k, '<<YOK>>')
        if hv != ov:
            print('  FARK  %-40s | H: %-35s | O: %-35s' % (k, str(hv)[:35], str(ov)[:35]))
    
    print('\nKRITIK ALANLAR:')
    cari_important = ['IsIndividualAcc','IsSubjectToEInvoice','IsSubjectToEShipment',
                      'FirstName','LastName','IdentityNum','TaxNumber','TaxOfficeCode',
                      'CustomerTypeCode','CurrencyCode','OfficeCode','CompanyCode',
                      'IsArrangeCommercialInvoice','DataLanguageCode','BarcodeTypeCode',
                      'CurrAccTypeCode','IsBlocked','IsLocked','MersisNum','TitleCode',
                      'PaymentTerm','ExchangeTypeCode','IsSendAdvertSMS','IsSendAdvertMail',
                      'IsVIP','VendorTypeCode']
    for k in cari_important:
        hv = curr_h.get(k, '<<YOK>>')
        ov = curr_o.get(k, '<<YOK>>')
        marker = 'FARK!' if hv != ov else '     '
        print('%s %-40s | H: %-35s | O: %-35s' % (marker, k, str(hv)[:35], str(ov)[:35]))

# ═══════════════════════════════════════════════════════
# SIPARIS
# ═══════════════════════════════════════════════════════
order_h = load('order_hamurlabs.json')
order_o = load('order_odoo.json')

skip_order = {'OrderHeaderID','ApplicationID','OrderNumber','OrderDate','OrderTime',
              'AverageDueDate','CurrAccCode','BillingPostalAddressID','ShippingPostalAddressID',
              'CreditableConfirmedDate','CreditableConfirmedUser','CreatedUserName',
              'CreatedDate','LastUpdatedUserName','LastUpdatedDate'}

print('\n' + '=' * 110)
print('SIPARIS KARSILASTIRMA')
print('=' * 110)

if order_h and order_o:
    all_keys = sorted(set(list(order_h.keys()) + list(order_o.keys())))
    
    print('\nFARKLAR:')
    for k in all_keys:
        if k in skip_order: continue
        hv = order_h.get(k, '<<YOK>>')
        ov = order_o.get(k, '<<YOK>>')
        if hv != ov:
            print('  FARK  %-40s | H: %-35s | O: %-35s' % (k, str(hv)[:35], str(ov)[:35]))
    
    print('\nKRITIK ALANLAR:')
    order_important = ['ModelType','OrderTypeCode','ProcessCode','IsCompleted','IsSalesViaInternet',
                       'ShipmentMethodCode','DeliveryCompanyCode','WarehouseCode','StoreCode',
                       'OfficeCode','POSTerminalID','TaxTypeCode','TaxExemptionCode',
                       'Description','InternalDescription','DocumentNumber',
                       'IsInclutedVat','IsCreditSale','IsOrderBase','IsSuspended',
                       'ExportFileNumber','ImportFileNumber','DocCurrencyCode','LocalCurrencyCode',
                       'ExchangeRate','CompanyCode','StoreTypeCode','ToWarehouseCode',
                       'OrdererCompanyCode','OrdererOfficeCode','OrdererStoreCode',
                       'IsCreditableConfirmed','IsClosed','UserLocked','IsLocked','IsPrinted']
    for k in order_important:
        hv = order_h.get(k, '<<YOK>>')
        ov = order_o.get(k, '<<YOK>>')
        marker = 'FARK!' if hv != ov else '     '
        print('%s %-40s | H: %-35s | O: %-35s' % (marker, k, str(hv)[:35], str(ov)[:35]))

# ═══════════════════════════════════════════════════════
# FATURA
# ═══════════════════════════════════════════════════════
inv_h = load('invoice_hamurlabs.json')
inv_o = load('invoice_odoo.json')

skip_inv = {'InvoiceHeaderID','InvoiceLineID','ApplicationID','OrderLineID',
            'InvoiceNumber','InvoiceDate','InvoiceTime','OperationDate','OperationTime',
            'JournalDate','AverageDueDate','Price','ItemCode','ColorCode','ItemDim1Code',
            'UsedBarcode','CurrAccCode','BillingPostalAddressID','ShippingPostalAddressID',
            'EMailAddress','SortOrder','CreatedUserName','CreatedDate','LastUpdatedUserName','LastUpdatedDate'}
skip_prefixes = ('Doc_', 'Loc_', 'Com_')

print('\n' + '=' * 110)
print('FATURA KARSILASTIRMA')
print('=' * 110)

if inv_h and inv_o:
    all_keys = sorted(set(list(inv_h.keys()) + list(inv_o.keys())))
    
    print('\nFARKLAR:')
    for k in all_keys:
        if k in skip_inv: continue
        if any(k.startswith(p) for p in skip_prefixes): continue
        hv = inv_h.get(k, '<<YOK>>')
        ov = inv_o.get(k, '<<YOK>>')
        if hv != ov:
            print('  FARK  %-40s | H: %-35s | O: %-35s' % (k, str(hv)[:35], str(ov)[:35]))
    
    print('\nKRITIK ALANLAR:')
    inv_important = ['InvoiceTypeCode','IsEInvoice','EInvoiceNumber','EInvoiceStatusCode',
                     'IsPostingJournal','SendInvoiceByEMail','IsCompleted','IsOrderBase',
                     'IsSalesViaInternet','ShipmentMethodCode','DeliveryCompanyCode',
                     'Description','InternalDescription','DocumentTypeCode','FormType',
                     'StoreTypeCode','StoreCode','WarehouseCode','POSTerminalID',
                     'TaxTypeCode','TaxExemptionCode','IsInclutedVat','IsDelivered',
                     'FiscalPrintedState','ExpenseTypeCode','TransTypeCode','ProcessCode',
                     'EInvoiceAliasCode','IsShipmentBase','IsReportedSaleBase','IsCreditSale',
                     'IsSuspended','IsProforma','IsLocked','IsPrinted','SendInvoiceBySMS']
    for k in inv_important:
        hv = inv_h.get(k, '<<YOK>>')
        ov = inv_o.get(k, '<<YOK>>')
        marker = 'FARK!' if hv != ov else '     '
        print('%s %-40s | H: %-35s | O: %-35s' % (marker, k, str(hv)[:35], str(ov)[:35]))

print('\n' + '=' * 110)
print('ANALIZ TAMAMLANDI')
print('=' * 110)
