# -*- coding: utf-8 -*-
"""cargo + cargo_ups A1 KABUL TESTLERI ortak tabani (test-muhendisi, Mod 1; kod yazilmadan once).

Bu dosya UYGULAMA kodu degildir. Gelistirici kendi tests/common.py dosyasini yazar; bu taban yalniz
``test_kabul_*`` dosyalari icindir ve gelistirici tarafindan silinmemeli / degistirilmemelidir
(sozlesme degisikligi gerekirse test-muhendisine geri gonderilir).

Icerik:
  * Duzgun-red mekanizmasi: ``cargo`` parcalari (model/grup) henuz yoksa her test ``setUp``'ta
    'OZELLIK YOK: ...' mesajiyla duser (sozdizimi/ice aktarma hatasi degil).
  * ``FakeProvider``: ``fixed`` (ve istege bagli ``base_on_rule``) tipli firmaya ``<tip>_cargo_send|cancel|find``
    ekler (``patch.object(..., create=True)``; tasarim 1.1).
  * ``NetBlock``: ``requests.Session.send`` yamasi; cekirdek testlerinde HTTP cagrisi YASAK (AssertionError).
  * ``_cargo_commit`` yamasi + olay zaman cizelgesi (KK-11).
  * Sentetik etiket PNG'si (UPS ornek yaniti DEGIL; sir/ kisisel veri yok) ve PDF yerlesim okuyucusu
    (PyPDF2/pypdf; icerik akisi icin kucuk bir CTM yorumlayicisi).
"""
import base64
import functools
import io
import re
import struct
from datetime import timedelta
from unittest.mock import patch

import requests

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, new_test_user
from odoo.tools import html2plaintext

# ---------------------------------------------------------------------------------------------
# Etiket PNG fikstur'u (tasarim 1.5: 771 x 1033 px, barkod blogu 176 x 951 px)
# ---------------------------------------------------------------------------------------------
LABEL_PX = (771, 1033)
BARCODE_BOX = (300, 41, 476, 992)      # x0, y0, x1, y1 (px, ust sinir dislayici) -> 176 x 951 px
PNG_MAGIC = b'\x89PNG\r\n\x1a\n'


@functools.lru_cache(maxsize=None)
def make_label_png(tag=0, size=LABEL_PX):
    """Sentetik UPS etiketi: beyaz zemin + barkod blogu + pakete ozgu isaret (tag). Gercek veri icermez."""
    from PIL import Image, ImageDraw
    image = Image.new('RGB', size, 'white')
    draw = ImageDraw.Draw(image)
    x0, y0, x1, y1 = BARCODE_BOX
    x = x0
    while x < x1 - 4:
        draw.rectangle([x, y0, x + 3, y1 - 1], fill='black')
        x += 8
    draw.rectangle([x1 - 4, y0, x1 - 1, y1 - 1], fill='black')
    # paket isareti: her pakette farkli konum -> PDF'te sayfa/goruntu siralamasi ayirt edilir
    draw.rectangle([20, 20 + 40 * tag, 70, 50 + 40 * tag], fill='black')
    buf = io.BytesIO()
    image.save(buf, 'PNG')
    return buf.getvalue()


def png_size(data):
    assert data[:8] == PNG_MAGIC, 'PNG degil'
    return struct.unpack('>II', data[16:24])


# ---------------------------------------------------------------------------------------------
# PDF okuyucu (etiket yerlesimi). DIKKAT: konteynerde pypdf yok, PyPDF2 2.12 var.
# ---------------------------------------------------------------------------------------------
def _pdf_reader(data):
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        from PyPDF2 import PdfReader
    return PdfReader(io.BytesIO(data))


def _mat_mul(m, n):
    return (m[0] * n[0] + m[1] * n[2], m[0] * n[1] + m[1] * n[3],
            m[2] * n[0] + m[3] * n[2], m[2] * n[1] + m[3] * n[3],
            m[4] * n[0] + m[5] * n[2] + n[4], m[4] * n[1] + m[5] * n[3] + n[5])


def _content_draws(content):
    """Icerik akisindan ``Do`` cagrilarini CTM ile cikarir: [(ad, (a, b, c, d, e, f))]."""
    text = content.decode('latin-1')
    text = re.sub(r'\((?:\\.|[^\\()])*\)', '()', text)      # dizgeler
    text = re.sub(r'<[0-9A-Fa-f\s]*>', '<>', text)           # hex dizgeler
    tokens = text.split()
    ctm, stack, operands, draws = (1, 0, 0, 1, 0, 0), [], [], []
    for token in tokens:
        if token == 'q':
            stack.append(ctm)
            operands = []
        elif token == 'Q':
            ctm = stack.pop() if stack else (1, 0, 0, 1, 0, 0)
            operands = []
        elif token == 'cm':
            if len(operands) >= 6:
                ctm = _mat_mul(tuple(float(x) for x in operands[-6:]), ctm)
            operands = []
        elif token == 'Do':
            if operands:
                draws.append((operands[-1].lstrip('/'), ctm))
            operands = []
        else:
            operands.append(token)
            if len(operands) > 16:
                operands = operands[-16:]
    return draws


def read_pdf(data):
    """-> [{'width': pt, 'height': pt, 'images': [{'name', 'x', 'y', 'w', 'h', 'px_w', 'px_h', 'rot'}]}]

    ``x, y`` sayfanin SOL ALT kosesinden pt; ``w, h`` yerlestirilen goruntunun pt boyutu; ``px_w, px_h`` goruntu
    XObject'inin /Width,/Height degerleri (PNG yeniden ornekleme kontrolu); ``rot`` donme/egim bileseni.
    """
    assert data[:5] == b'%PDF-', 'PDF degil'
    reader = _pdf_reader(data)
    pages = []
    for page in reader.pages:
        box = page.mediabox
        info = {'width': float(box.width), 'height': float(box.height), 'images': []}
        contents = page.get_contents()
        raw = contents.get_data() if contents is not None else b''
        resources = page.get('/Resources')
        xobjects = {}
        if resources is not None:
            resources = resources.get_object()
            if '/XObject' in resources:
                xobjects = resources['/XObject'].get_object()
        for name, ctm in _content_draws(raw):
            xobj = xobjects.get('/' + name)
            xobj = xobj.get_object() if xobj is not None else {}
            info['images'].append({
                'name': name, 'x': ctm[4], 'y': ctm[5], 'w': ctm[0], 'h': ctm[3],
                'rot': abs(ctm[1]) + abs(ctm[2]),
                'px_w': int(xobj.get('/Width', 0)), 'px_h': int(xobj.get('/Height', 0)),
            })
        pages.append(info)
    return pages


# ---------------------------------------------------------------------------------------------
# Ag engeli ve sahte saglayici
# ---------------------------------------------------------------------------------------------
class NetBlock:
    """``requests.Session.send`` yamasi. ``router(request, **kwargs)`` verilmezse her cagri AssertionError'dir."""

    def __init__(self, test, router=None):
        self.requests = []          # [{'method','url','headers','body','timeout'}]
        self.unexpected = []
        self.router = router
        self._patcher = patch.object(requests.Session, 'send', self._send(), create=False)
        self._patcher.start()
        test.addCleanup(self._patcher.stop)

    def _send(self):
        block = self

        def send(session, request, **kwargs):
            body = request.body
            if isinstance(body, bytes):
                body = body.decode('utf-8', 'replace')
            block.requests.append({'method': request.method, 'url': request.url,
                                   'headers': dict(request.headers), 'body': body,
                                   'timeout': kwargs.get('timeout')})
            if block.router is None:
                block.unexpected.append(request.url)
                raise AssertionError('Beklenmeyen HTTP cagrisi (kabul testi ag engeli): %s %s' % (request.method, request.url))
            return block.router(request, **kwargs)
        return send


class FakeProvider:
    """``<tip>_cargo_send|cancel|find`` sahte saglayici (tasarim 1.1/4.5).

    ``plan[op]``: dict | callable(shipment) -> dict | list (sirayla tuketilir, sonuncu tekrarlanir) | Exception ornegi.
    Her cagri ``calls`` listesine, cagri ANINDAKI kayit ozeti ile yazilir (state/sent_at/name SQL'den: flush sonrasi).
    """

    OPS = ('send', 'cancel', 'find')

    def __init__(self, test, types=('fixed',)):
        self.test = test
        self.timeline = test.timeline
        self.calls = []
        self.counter = 0
        self.hook = {}               # op -> callable(shipment): saglayici icinde calisir (eszamanlilik/siralama)
        self.plan = {
            'send': lambda shipment: self.ok_send(shipment=shipment),
            'cancel': {'status': 'ok', 'error_code': '', 'error_message': ''},
            'find': {'status': 'not_found', 'tracking_ref': '', 'count': 0, 'error_message': ''},
        }
        Carrier = type(test.env['delivery.carrier'])
        for ptype in types:
            for op in self.OPS:
                patcher = patch.object(Carrier, '%s_cargo_%s' % (ptype, op), self._method(op), create=True)
                patcher.start()
                test.addCleanup(patcher.stop)

    # -- sonuc ureticiler
    def ok_send(self, tracking=None, n=None, shipment=None):
        self.counter += 1
        n = n if n is not None else (shipment.sudo().package_count if shipment else 1)
        return {'status': 'ok', 'tracking_ref': tracking or '1ZKABUL%07d' % self.counter,
                'labels': [make_label_png(i) for i in range(max(int(n or 1), 1))],
                'error_code': '', 'error_message': ''}

    @staticmethod
    def err_send(code='9001', message='Adres hatali'):
        return {'status': 'error', 'tracking_ref': '', 'labels': [], 'error_code': code, 'error_message': message}

    @staticmethod
    def uncertain_send(message='Zaman asimi'):
        return {'status': 'uncertain', 'tracking_ref': '', 'labels': [], 'error_code': '', 'error_message': message}

    @staticmethod
    def found(tracking='1ZBULUNDU0001', count=1):
        return {'status': 'found', 'tracking_ref': tracking, 'count': count, 'error_message': ''}

    @staticmethod
    def not_found():
        return {'status': 'not_found', 'tracking_ref': '', 'count': 0, 'error_message': ''}

    @staticmethod
    def find_error(message='Sorgu hatasi'):
        return {'status': 'error', 'tracking_ref': '', 'count': 0, 'error_message': message}

    # -- cagri kaydi
    def _method(self, op):
        provider = self

        def method(carrier, shipment, *args, **kwargs):
            return provider._handle(op, carrier, shipment)
        return method

    def _handle(self, op, carrier, shipment):
        shipment = shipment.sudo()
        shipment.env.flush_all()
        shipment.env.cr.execute('SELECT state, sent_at, name FROM cargo_shipment WHERE id = %s', [shipment.id])
        state, sent_at, name = shipment.env.cr.fetchone()
        self.calls.append({
            'op': op, 'id': shipment.id, 'carrier_id': carrier.id, 'state': state, 'sent_at': sent_at, 'name': name,
            'recipient_name': shipment.recipient_name, 'recipient_phone': shipment.recipient_phone,
            'recipient_street': shipment.recipient_street, 'recipient_district': shipment.recipient_district,
            'state_code': shipment.recipient_state_id.code, 'area_code': shipment.area_id.area_code,
            'package_count': shipment.package_count, 'package_weight': shipment.package_weight,
            'cod_amount': shipment.cod_amount, 'cod_method': shipment.cod_method,
            'origin_ref': shipment.origin_ref, 'invoice_no': shipment.invoice_no,
            'test_mode': shipment.test_mode, 'tracking_ref': shipment.tracking_ref,
        })
        self.timeline.append(('provider', op, shipment.id))
        if self.hook.get(op):
            self.hook[op](shipment)
        result = self.plan[op]
        if isinstance(result, list):
            result = result.pop(0) if len(result) > 1 else result[0]
        if callable(result):
            result = result(shipment)
        if isinstance(result, BaseException):
            raise result
        return dict(result)

    def of(self, op):
        return [c for c in self.calls if c['op'] == op]

    def count(self, op=None):
        return len(self.calls) if op is None else len(self.of(op))


# ---------------------------------------------------------------------------------------------
# Taban test sinifi
# ---------------------------------------------------------------------------------------------
class CargoKabulCase(TransactionCase):
    """Cekirdek kabul testi tabani.

    Sinif ``REQUIRES_MODELS`` / ``REQUIRES_XMLIDS`` eksikse, HER test ``setUp``'ta 'OZELLIK YOK' ile duser.
    ``FAKE_COMMIT``: ``cargo.shipment._cargo_commit`` yamasi (gercek commit yok; olaylar ``timeline``'a yazilir).
    """

    REQUIRES_MODELS = ('cargo.shipment', 'cargo.area')
    REQUIRES_XMLIDS = ('cargo.group_cargo_user', 'cargo.group_cargo_manager')
    FAKE_COMMIT = True
    PROVIDER_TYPES = ('fixed',)
    _area_seq = 920000
    eksik = ()

    # -- kurulum
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.eksik = cls._eksik_parcalar()
        if not cls.eksik:
            cls._kur()

    @classmethod
    def _eksik_parcalar(cls):
        eksik = []
        for model in cls.REQUIRES_MODELS:
            if model not in cls.env.registry:
                eksik.append('model %s tanimli degil' % model)
        for xmlid in cls.REQUIRES_XMLIDS:
            if not cls.env.ref(xmlid, raise_if_not_found=False):
                eksik.append('%s yok' % xmlid)
        return eksik

    @classmethod
    def mk_user(cls, login, groups):
        return new_test_user(cls.env, login='kabul_%s' % login, groups=groups)

    @classmethod
    def st(cls, code):
        return cls.env.ref('base.state_tr_%s' % code)

    @classmethod
    def _service_product(cls):
        product = cls.env.ref('delivery.product_product_delivery', raise_if_not_found=False)
        if product:
            return product
        return cls.env['product.product'].create({'name': 'Kargo hizmeti (kabul)', 'type': 'service'})

    @classmethod
    def make_carrier(cls, name, ptype='fixed', cod=True, **kw):
        vals = {'name': name, 'delivery_type': ptype, 'product_id': cls._service_product().id,
                'integration_level': 'rate', 'prod_environment': False}
        if 'cargo_cod_enabled' in cls.env['delivery.carrier']._fields:
            vals['cargo_cod_enabled'] = cod
        vals.update(kw)
        return cls.env['delivery.carrier'].create(vals)

    @classmethod
    def make_area(cls, state_code, name, provider='fixed', alias='', code=None):
        CargoKabulCase._area_seq += 1
        return cls.env['cargo.area'].create({
            'provider': provider, 'state_id': cls.st(state_code).id, 'name': name,
            'alias_names': alias, 'city_code': int(state_code),
            'area_code': code or CargoKabulCase._area_seq,
        })

    @classmethod
    def _kur(cls):
        env = cls.env
        cls.tr = env.ref('base.tr')
        cls.company = env.company
        cls.company.write({
            'name': 'Kabul Test Firmasi', 'street': 'Test Cad. No:1', 'street2': 'Kat 2', 'city': 'Kadikoy',
            'zip': '34710', 'state_id': cls.st('34').id, 'country_id': cls.tr.id,
            'phone': '02161234567', 'email': 'firma@example.com',
        })
        if 'cargo.area' in env.registry:      # G2'den once (yalniz G1 testleri) alan modeli yok
            cls.area_cankaya = cls.make_area('06', 'CANKAYA')
            cls.area_kadikoy = cls.make_area('34', 'KADIKOY')
            cls.area_umraniye = cls.make_area('34', 'UMRANIYE')
        cls.carrier = cls.make_carrier('KK Kargo (nakit ODP)', cod=True)
        cls.carrier_y = cls.make_carrier('KK Kargo Y', cod=True)
        cls.carrier_nocod = cls.make_carrier('KK Kargo ODPsiz', cod=False)
        cls.company.write({'cargo_default_carrier_id': cls.carrier.id, 'cargo_default_weight': 1.0,
                           'cargo_cod_max_amount': 0.0, 'cargo_label_size': '10x15'})
        cls.user = cls.mk_user('kargo_kullanici', 'base.group_user,cargo.group_cargo_user')
        cls.manager = cls.mk_user('kargo_yonetici', 'base.group_user,cargo.group_cargo_manager')
        cls.plain = cls.mk_user('duz_kullanici', 'base.group_user')
        cls.plain_sales = cls.mk_user('satis_kullanici', 'base.group_user,sales_team.group_sale_salesman')

    def setUp(self):
        super().setUp()
        if self.eksik:
            self.fail('OZELLIK YOK: ' + '; '.join(self.eksik)
                      + ' (cargo modulu ilgili gorev tamamlanana kadar kirmizi beklenir)')
        self.timeline = []
        self.net = NetBlock(self)
        self.provider = FakeProvider(self, types=self.PROVIDER_TYPES)
        if self.FAKE_COMMIT and 'cargo.shipment' in self.env.registry:
            self._patch_commit()
        self.addCleanup(self._ag_temiz_mi)

    def _ag_temiz_mi(self):
        if self.net.router is None:
            self.assertEqual(self.net.requests, [], 'cekirdek testlerinde HTTP cagrisi yapilmamali')

    def _patch_commit(self):
        timeline = self.timeline

        def fake_commit(this, *args, **kwargs):
            this.env.flush_all()
            this.env.cr.execute('SELECT id, state, sent_at, name FROM cargo_shipment')
            timeline.append(('commit', {r[0]: (r[1], r[2], r[3]) for r in this.env.cr.fetchall()}))
        patcher = patch.object(type(self.env['cargo.shipment']), '_cargo_commit', fake_commit, create=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    # -- kayit uretimi
    def vals(self, **over):
        vals = {
            'carrier_id': self.carrier.id, 'recipient_name': 'Ali Veli', 'recipient_phone': '05321234567',
            'recipient_email': 'ali@example.com', 'recipient_street': 'Ataturk Mah. Gul Sk. No:5 D:3',
            'recipient_state_id': self.st('06').id, 'recipient_district': 'Cankaya',
            'package_count': 1, 'package_weight': 1.5, 'description': 'Test esya',
        }
        vals.update(over)
        return vals

    def mk(self, user=None, **over):
        """draft gonderi (varsayilan: kargo kullanicisi olarak)."""
        if 'cargo.shipment' not in self.env.registry:
            self.fail('OZELLIK YOK: model cargo.shipment tanimli degil (G3)')
        return self.env['cargo.shipment'].with_user(user or self.user).create(self.vals(**over))

    def sent(self, user=None, **over):
        """kargo kullanicisi olarak olusturup 'Gonder' yapar; ``created`` beklenir."""
        shipment = self.mk(user=user, **over)
        shipment.action_send()
        self.assertEqual(shipment.state, 'created', 'on kosul: sahte saglayici ok donmeli')
        return shipment

    # -- yardimcilar
    def chatter(self, shipment):
        """Gonderinin chatter metni (duz metin, tek dize)."""
        messages = shipment.sudo().message_ids
        return '\n'.join(html2plaintext(m.body or '') for m in messages)

    def attachments(self, shipment, mimetype=None):
        domain = [('res_model', '=', 'cargo.shipment'), ('res_id', '=', shipment.id)]
        if mimetype:
            domain.append(('mimetype', '=', mimetype))
        return self.env['ir.attachment'].sudo().search(domain, order='id')

    def try_call(self, func):
        """-> (sonuc, hata). Kullanici hatasi savepoint ile geri alinir; hata nesnesi doner."""
        try:
            with self.env.cr.savepoint():
                return func(), None
        except UserError as error:
            return None, error

    def assert_user_error(self, func, regex=None, msg=None):
        with self.assertRaises(UserError, msg=msg) as ctx:
            func()
        if regex:
            self.assertRegex(str(ctx.exception), regex, msg)
        return ctx.exception

    def no_provider_calls(self, msg='disariya cagri yapilmamali'):
        self.assertEqual(self.provider.calls, [], msg)

    def minutes_ago(self, minutes):
        return fields.Datetime.now() - timedelta(minutes=minutes)

    @staticmethod
    def b64(data):
        return base64.b64encode(data)
