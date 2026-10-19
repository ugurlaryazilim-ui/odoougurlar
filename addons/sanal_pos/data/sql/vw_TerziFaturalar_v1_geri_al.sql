/* Geri alma: vw_TerziFaturalar'ı v2 öncesi (orijinal) tanıma döndürür. */
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
    sp.FirstLastName AS SatisPersoneli

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

WHERE ih.IsReturn = 0;
