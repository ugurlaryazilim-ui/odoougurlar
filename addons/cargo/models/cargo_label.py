# -*- coding: utf-8 -*-
"""Etiket PDF'i: saf fonksiyon, Odoo'dan bağımsız (02-tasarim §1.5, K-23).

Etiket PNG'si yeniden örneklenmeden, kargo firmasının referans basım boyutunda (96,5 x 137,2 mm) yerleştirilir.
"""
import io

from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

MM = 72.0 / 25.4
# NEDEN: referans boyut firmanın C# örneğindeki DrawImage(image, 10, 10, 380, 540) çağrısından gelir; .NET
# yazıcı birimi 1/100 inçtir, yani 3,80 x 5,40 inç. 771x1033 px PNG bu boyutta ~203 yatay / ~191 dikey dpi olur ve
# barkod 2,2 x 12,6 cm çıkar (K-23). Oran korunarak 10 cm genişliğe sığdırılırsa barkod 12 cm'nin altında kalır.
# DIKKAT: boyutu değiştirmeden önce test_kabul_etiket::test_barkod_fiziksel_olculer çalıştır; kurye cihazı okuması
# yalnız elle doğrulanır (CD-5).
IMAGE_SIZE = (3.8 * 72.0, 5.4 * 72.0)
PAGE_SIZES = {'10x15': (100 * MM, 150 * MM), 'a4': (210 * MM, 297 * MM)}
A4_MARGIN = 10 * MM


def build_label_pdf(images, page_size='10x15'):
    """PNG baytları listesinden PDF baytları üretir; sayfa başına tek etiket.

    ``page_size``: ``10x15`` (etiket ortalanır) ya da ``a4`` (sol üst, 1 cm kenar boşluğu).
    """
    page_w, page_h = PAGE_SIZES[page_size]
    img_w, img_h = IMAGE_SIZE
    if page_size == 'a4':
        x, y = A4_MARGIN, page_h - A4_MARGIN - img_h
    else:
        x, y = (page_w - img_w) / 2, (page_h - img_h) / 2
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=(page_w, page_h))
    for data in images:
        # NEDEN: mask='auto' saydam PNG'de arka planın siyaha dönmesini önler.
        pdf.drawImage(ImageReader(io.BytesIO(data)), x, y, width=img_w, height=img_h, mask='auto')
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()
