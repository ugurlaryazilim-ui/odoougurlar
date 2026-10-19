/* vw_TerziFaturalar v2 (sanal_pos için)
   - İlk 18 sütun önceki tanımla birebir aynı (terzi modülü değişmeden çalışır).
   - Sona eklenenler: SatirTutari, ParaBirimi, FaturaToplam, MusteriEposta,
     FaturaAdresi, FaturaIlKodu, FaturaIlceKodu, FaturaGSMNo.
   - Tutar kaynağı: trInvoiceLineCurrency.NetAmount (indirimler düşülmüş, KDV dahil),
     yalnız faturanın belge para birimindeki satır (çift sayımı önler).
     Doğrulama: UGR2026000012587 -> 4500,45 + 1799,64 + 2699,91 = 9000,00.
   - Geri alma: sql/vw_TerziFaturalar_v1_geri_al.sql
*/
ALTER VIEW dbo.vw_TerziFaturalar AS
SELECT
    ih.InvoiceHeaderID,
    LTRIM(RTRIM(ih.EInvoiceNumber)) AS UGRFaturaNo,
    ih.InvoiceNumber AS IcFaturaNo,
    ih.InvoiceDate AS FaturaTarihi,

    ih.CurrAccCode AS MusteriKodu,
    cad.CurrAccDescription AS MusteriAdi,
    LTRIM(RTRIM(tel.CommAddress)) AS MusteriCep,

    il.InvoiceLineID AS FaturaSatirID,
    il.SortOrder AS SatirNo,
    il.ItemCode AS UrunKodu,
    il.UsedBarcode AS Barkod,
    il.Qty1 AS Adet,
    il.ColorCode,
    il.ItemDim1Code,
    il.ItemDim2Code,
    il.ItemDim3Code,

    il.SalespersonCode AS SatisPersonelKodu,
    sp.FirstLastName AS SatisPersoneli,

    -- ===== v2: yeni sütunlar =====
    CAST(satir.NetAmount AS decimal(18,2)) AS SatirTutari,
    ih.DocCurrencyCode AS ParaBirimi,
    CAST(top_.FaturaToplam AS decimal(18,2)) AS FaturaToplam,
    COALESCE(NULLIF(LTRIM(RTRIM(ih.EMailAddress)), ''),
             LTRIM(RTRIM(mail.CommAddress))) AS MusteriEposta,
    LTRIM(RTRIM(adr.Address)) AS FaturaAdresi,
    adr.CityCode AS FaturaIlKodu,
    adr.DistrictCode AS FaturaIlceKodu,
    NULLIF(LTRIM(RTRIM(ih.GSMNo)), '') AS FaturaGSMNo

FROM dbo.trInvoiceHeader ih
INNER JOIN dbo.trInvoiceLine il
    ON il.InvoiceHeaderID = ih.InvoiceHeaderID

LEFT JOIN dbo.cdCurrAccDesc cad
    ON cad.CurrAccTypeCode = ih.CurrAccTypeCode
   AND cad.CurrAccCode = ih.CurrAccCode
   AND cad.LangCode = 'TR'

LEFT JOIN dbo.cdSalesperson sp
    ON sp.SalespersonCode = il.SalespersonCode

-- Müşterinin cep telefonu:
--   1) Cep numarasına benzeyenler (05.., 5.., +905.., 905..) her zaman önce
--   2) Sonra alan sırası: Özel Mobil (7), Cep (5), İş Mobil (6), Ev (4), Telefon (1)
OUTER APPLY (
    SELECT TOP 1 c.CommAddress
    FROM dbo.prCurrAccCommunication AS c WITH (NOLOCK)
    WHERE c.CurrAccTypeCode = ih.CurrAccTypeCode
      AND c.CurrAccCode = ih.CurrAccCode
      AND c.CommunicationTypeCode IN (7, 5, 6, 4, 1)
      AND LTRIM(RTRIM(c.CommAddress)) <> ''
    ORDER BY
      CASE WHEN REPLACE(c.CommAddress, ' ', '') LIKE '05%'
             OR REPLACE(c.CommAddress, ' ', '') LIKE '5%'
             OR REPLACE(c.CommAddress, ' ', '') LIKE '+905%'
             OR REPLACE(c.CommAddress, ' ', '') LIKE '905%' THEN 0 ELSE 1 END,
      CASE c.CommunicationTypeCode WHEN 7 THEN 0 WHEN 5 THEN 1 WHEN 6 THEN 2 WHEN 4 THEN 3 ELSE 4 END
) AS tel

-- v2: satır tutarı (belge para biriminde)
OUTER APPLY (
    SELECT TOP 1 ilc.NetAmount
    FROM dbo.trInvoiceLineCurrency AS ilc WITH (NOLOCK)
    WHERE ilc.InvoiceLineID = il.InvoiceLineID
      AND ilc.CurrencyCode = ih.DocCurrencyCode
) AS satir

-- v2: fatura genel toplamı (tüm satırlar, belge para biriminde)
OUTER APPLY (
    SELECT SUM(ilc.NetAmount) AS FaturaToplam
    FROM dbo.trInvoiceLine AS il2 WITH (NOLOCK)
    INNER JOIN dbo.trInvoiceLineCurrency AS ilc WITH (NOLOCK)
        ON ilc.InvoiceLineID = il2.InvoiceLineID
       AND ilc.CurrencyCode = ih.DocCurrencyCode
    WHERE il2.InvoiceHeaderID = ih.InvoiceHeaderID
) AS top_

-- v2: fatura başlığında e-posta yoksa cari kartındaki e-posta (iletişim tipi 3)
OUTER APPLY (
    SELECT TOP 1 c.CommAddress
    FROM dbo.prCurrAccCommunication AS c WITH (NOLOCK)
    WHERE c.CurrAccTypeCode = ih.CurrAccTypeCode
      AND c.CurrAccCode = ih.CurrAccCode
      AND c.CommunicationTypeCode = 3
      AND LTRIM(RTRIM(c.CommAddress)) LIKE '%_@_%._%'
    ORDER BY c.LastUpdatedDate DESC
) AS mail

-- v2: fatura adresi
LEFT JOIN dbo.prCurrAccPostalAddress adr WITH (NOLOCK)
    ON adr.PostalAddressID = ih.BillingPostalAddressID

WHERE ih.IsReturn = 0;
