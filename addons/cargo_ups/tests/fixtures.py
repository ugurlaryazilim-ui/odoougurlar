# -*- coding: utf-8 -*-
"""G9 birim testi fikstürleri: UPS'in örnek yanıt dökümlerinin (Domestic Shipping API/soapresponseenvelop.txt,
loginresponsesoap.txt) YAPISI aynen korunmuştur (girinti, boş öğe, &amp; kaçışı).

NEDEN: değerler uydurmadır. Gerçek SessionID, LabelKey'li bağlantı ve ShipmentNo silindi; 90 KB etiket
PNG'si 1x1 sentetik PNG ile değiştirildi. Dökümün utf-16 bildirimi tel üzerindeki utf-8 ile değiştirildi.
"""

TINY_PNG_B64 = ('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==')
FIXTURE_SESSION = 'FIXTURE-OTURUM-G9'
FIXTURE_SHIPMENT_NO = '1ZFIXTR0000000001'

LOGIN_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <Login_Type1Response xmlns="https://ws.ups.com.tr/wsCreateShipment">
      <Login_Type1Result>
        <SessionID>%s</SessionID>
        <ErrorCode>0</ErrorCode>
        <ErrorDefinition />
      </Login_Type1Result>
    </Login_Type1Response>
  </soap:Body>
</soap:Envelope>""" % FIXTURE_SESSION

CREATE_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <soap:Body>
    <CreateShipment_Type3Response xmlns="https://ws.ups.com.tr/wsCreateShipment">
      <CreateShipment_Type3Result>
        <ShipmentNo>%(no)s</ShipmentNo>
        <LinkForLabelPrinting>https://ws.ups.com.tr/UmoWSLabel/Barcode.aspx?ShipmentNo=%(no)s&amp;Type=Print</LinkForLabelPrinting>
        <BarkodArrayPng>
          <string>%(png)s</string>
        </BarkodArrayPng>
        <ErrorCode>0</ErrorCode>
        <ErrorDefinition />
      </CreateShipment_Type3Result>
    </CreateShipment_Type3Response>
  </soap:Body>
</soap:Envelope>""" % {'no': FIXTURE_SHIPMENT_NO, 'png': TINY_PNG_B64}
