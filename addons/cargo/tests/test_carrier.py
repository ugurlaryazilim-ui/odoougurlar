# -*- coding: utf-8 -*-
"""G1 birim testleri: delivery.carrier uzantısı (yönetilen firma, _cargo_call, rate kısıtı, ODP bayrak alanları)."""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import tagged

from .common import CargoTestCase

COD_FIELDS = ('cargo_cod_enabled', 'cargo_cod_allow_cash', 'cargo_cod_allow_card', 'cargo_cod_allow_check')


@tagged('post_install', '-at_install', 'cargo')
class TestCarrierExtension(CargoTestCase):

    def test_odp_alanlari_gruplu_ve_sizdirmaz(self):
        """Alan listesiz read/search_read ve fields_get yetkisiz kullanıcıya ODP bayrağı vermez."""
        Carrier = self.env['delivery.carrier']
        # satış kullanıcısı delivery.zip.prefix gibi ilişkili modelleri de okuyabildiğinden alan listesiz okur
        row = self.carrier.with_user(self.plain_sales).read()[0]
        rows = Carrier.with_user(self.plain_sales).search_read([('id', '=', self.carrier.id)])
        for name in COD_FIELDS:
            self.assertNotIn(name, row, name)
            self.assertNotIn(name, rows[0], name)
        # kargo kullanıcısı yalnız firma kaydını okur (zip/kural tabloları yok): fields_get'ten türeyen liste
        described = self.carrier.with_user(self.user).fields_get()
        for name in COD_FIELDS:
            self.assertNotIn(name, described, name)
        plain_fields = [n for n, f in described.items() if f['type'] not in ('one2many', 'many2many')]
        row = self.carrier.with_user(self.user).read(plain_fields)[0]
        for name in COD_FIELDS:
            self.assertNotIn(name, row, name)

    def test_odp_alanlari_web_read_ve_arama(self):
        for user in (self.user, self.plain_sales):
            carrier = self.carrier.with_user(user)
            for name in COD_FIELDS:
                with self.assertRaises(AccessError, msg=name):
                    carrier.web_read({name: {}})
                with self.assertRaises(AccessError, msg=name):
                    self.env['delivery.carrier'].with_user(user).web_search_read(
                        [('id', '=', self.carrier.id)], {name: {}})
                with self.assertRaises(AccessError, msg=name):
                    # alana göre arama da değer sızdırır (varlık/yokluk)
                    self.env['delivery.carrier'].with_user(user).search([(name, '=', True)])

    def test_yonetici_odp_alanlarini_gorur(self):
        described = self.carrier.with_user(self.manager).fields_get()
        self.assertTrue(set(COD_FIELDS) <= set(described))
        row = self.carrier.with_user(self.manager).read(list(COD_FIELDS))[0]
        self.assertTrue(row['cargo_cod_enabled'])

    def test_kullanici_firma_yazamaz(self):
        with self.assertRaises(AccessError):
            self.carrier.with_user(self.user).write({'name': 'Degisti'})
        with self.assertRaises(AccessError):
            self.env['delivery.carrier'].with_user(self.user).create({
                'name': 'Yeni', 'delivery_type': 'fixed', 'product_id': self._service_product().id})

    def test_yonetici_firma_olusturamaz_silemez(self):
        # NEDEN: kargo yöneticisi mevcut firmanın bayrak/kimlik alanlarını yazar; firma kaydı açıp silmek
        # satış yöneticisinin işidir (ACL 1,1,0,0).
        with self.assertRaises(AccessError):
            self.env['delivery.carrier'].with_user(self.manager).create({
                'name': 'Yeni', 'delivery_type': 'fixed', 'product_id': self._service_product().id})
        with self.assertRaises(AccessError):
            self.carrier.with_user(self.manager).unlink()

    def test_yonetilen_firma_tipleri_ve_hesaplanan_alan(self):
        self.stub_provider('fixed', ops=('send',))
        self.assertIn('fixed', self.env['delivery.carrier']._cargo_managed_types())
        self.assertNotIn('base_on_rule', self.env['delivery.carrier']._cargo_managed_types())
        self.assertTrue(self.carrier.cargo_managed)
        other = self.env['delivery.carrier'].create({
            'name': 'Kural', 'delivery_type': 'base_on_rule', 'product_id': self._service_product().id})
        self.assertFalse(other.cargo_managed)

    def test_yonetilen_firmada_stock_delivery_gonder_iptal_engellenir(self):
        """Ö3: yönetilen firmada Odoo'nun send_shipping/cancel_shipment yolları açık hata verir (traceback değil)."""
        no_picking = self.env['stock.picking']
        self.assertEqual(self.carrier.send_shipping(no_picking), [])     # yönetilmeyen: Odoo davranışı
        calls = self.stub_provider('fixed', ops=('send', 'cancel'))
        with self.assertRaisesRegex(UserError, 'kargo gönderisi formundan gönderin'):
            self.carrier.send_shipping(no_picking)
        with self.assertRaisesRegex(UserError, 'Kargo gönderisi formundan iptal edin'):
            self.carrier.cancel_shipment(no_picking)
        self.assertEqual(calls, [])

    def test_yonetilmeyen_tipte_cargo_call_user_error(self):
        other = self.env['delivery.carrier'].create({
            'name': 'Kural', 'delivery_type': 'base_on_rule', 'product_id': self._service_product().id})
        with self.assertRaises(UserError):
            other._cargo_call('send', 'x')

    def test_bilinmeyen_islem_reddedilir(self):
        # NEDEN: op dizgesi getattr'a gidiyor; yalnız bilinen sağlayıcı işlemleri çağrılabilir.
        self.stub_provider('fixed', ops=('send',))
        with self.assertRaises(UserError):
            self.carrier._cargo_call('unlink')
        with self.assertRaises(UserError):
            self.carrier._cargo_call('send_to_shipper')

    def test_cargo_call_argumanlari_iletir_prod_bayragi_engellemez(self):
        calls = self.stub_provider('fixed', ops=('send', 'cod_code'), result={'status': 'ok', 'tracking_ref': 'T'})
        self.assertFalse(self.carrier.prod_environment)
        self.assertEqual(self.carrier._cargo_call('send', 'kayit')['tracking_ref'], 'T')
        self.carrier.prod_environment = True
        self.carrier._cargo_call('cod_code', 'cash')
        self.assertEqual(calls, [('send', ('kayit',)), ('cod_code', ('cash',))])

    def test_rate_kisiti_yalniz_yonetilen_tipte(self):
        self.stub_provider('fixed', ops=('send',))
        with self.assertRaises(ValidationError):
            self.carrier.integration_level = 'rate_and_ship'
        # sağlayıcı yoksa (yönetilmeyen) rate_and_ship serbest kalır
        other = self.env['delivery.carrier'].create({
            'name': 'Kural', 'delivery_type': 'base_on_rule', 'integration_level': 'rate_and_ship',
            'product_id': self._service_product().id})
        self.assertEqual(other.integration_level, 'rate_and_ship')

    def test_onchange_yonetilen_tipte_rate_secer(self):
        self.stub_provider('fixed', ops=('send',))
        carrier = self.env['delivery.carrier'].new({'name': 'Yeni', 'integration_level': 'rate_and_ship'})
        carrier.delivery_type = 'fixed'
        carrier._onchange_delivery_type_cargo()
        self.assertEqual(carrier.integration_level, 'rate')

    def test_odp_varsayilanlari_yeni_firmada(self):
        fresh = self.env['delivery.carrier'].create({
            'name': 'Varsayilan', 'delivery_type': 'fixed', 'integration_level': 'rate',
            'product_id': self._service_product().id})
        self.assertEqual([fresh[name] for name in COD_FIELDS], [False, True, False, False])


@tagged('post_install', '-at_install', 'cargo')
class TestCarrierProtectedFields(CargoTestCase):
    """05-guvenlik O-1: yönetilen firmanın korunan alanlarını yalnız Kargo / Yönetici yazar (stok/satış yöneticisi değil)."""

    @classmethod
    def _kur(cls):
        super()._kur()
        cls.stock_manager = cls.mk_user('o1_stok', 'base.group_user,stock.group_stock_manager')
        cls.sale_manager = cls.mk_user('o1_satis', 'base.group_user,sales_team.group_sale_manager')
        cls.stock_cargo_manager = cls.mk_user(
            'o1_stok_kargo', 'base.group_user,stock.group_stock_manager,cargo.group_cargo_manager')
        cls.free = cls.make_carrier('Serbest kural', ptype='base_on_rule')

    def setUp(self):
        super().setUp()
        # NEDEN: CargoTestCase sağlayıcı yamalamaz; 'fixed' ancak <tip>_cargo_send varken yönetilendir.
        self.stub_provider('fixed', ops=('send',))

    def protected_values(self):
        return {
            'prod_environment': True, 'delivery_type': 'base_on_rule', 'integration_level': 'rate',
            'active': False, 'company_id': self.env.company.id,
            'product_id': self.env['product.product'].create({'name': 'Baska hizmet', 'type': 'service'}).id,
        }

    def test_korunan_alanlar_stok_ve_satis_yoneticisi_yazamaz(self):
        for user in (self.stock_manager, self.sale_manager):
            for field, value in self.protected_values().items():
                with self.subTest(user=user.login, field=field), self.assertRaises(AccessError):
                    self.carrier.with_user(user).write({field: value})
        self.assertFalse(self.carrier.prod_environment)
        self.assertTrue(self.carrier.active)
        self.assertEqual(self.carrier.delivery_type, 'fixed')
        # korunmayan alan (ad) serbest kalır
        self.carrier.with_user(self.stock_manager).write({'name': 'KK Kargo (yeni ad)'})

    def test_korunan_alanlar_kargo_yoneticisi_yazar(self):
        self.carrier.with_user(self.manager).write({'prod_environment': True})
        self.assertTrue(self.carrier.prod_environment)
        self.carrier.with_user(self.stock_cargo_manager).write({'active': False})
        self.assertFalse(self.carrier.active)

    def test_yonetilen_firma_acma_silme_yalniz_kargo_yoneticisi(self):
        vals = {'name': 'Yeni yonetilen', 'delivery_type': 'fixed', 'integration_level': 'rate',
                'product_id': self._service_product().id}
        for user in (self.stock_manager, self.sale_manager):
            with self.subTest(user=user.login):
                with self.assertRaises(AccessError):
                    self.env['delivery.carrier'].with_user(user).create(dict(vals))
                with self.assertRaises(AccessError):
                    self.carrier_y.with_user(user).unlink()
        # yönetilmeyen firmayı yönetilen tipe çevirmek de korunur
        with self.assertRaises(AccessError):
            self.free.with_user(self.stock_manager).write({'delivery_type': 'fixed'})
        created = self.env['delivery.carrier'].with_user(self.stock_cargo_manager).create(dict(vals))
        created.with_user(self.stock_cargo_manager).unlink()
        self.assertFalse(created.exists())

    def test_yonetilmeyen_firma_serbest(self):
        self.free.with_user(self.stock_manager).write({'prod_environment': True, 'active': False})
        self.assertFalse(self.free.active)
        other = self.env['delivery.carrier'].with_user(self.stock_manager).create({
            'name': 'Serbest 2', 'delivery_type': 'base_on_rule', 'product_id': self._service_product().id})
        other.unlink()
        self.assertFalse(other.exists())

    def test_stok_yoneticisi_firma_cogaltabilir_gizli_alan_kopyalanmaz(self):
        """groups'lu alanlar (ODP bayrakları) üyesi olmayanın kopyasını AccessError'a düşürmez; varsayılanı alır."""
        self.free.sudo().write({'cargo_cod_enabled': True, 'cargo_cod_allow_card': True})
        copy = self.free.with_user(self.stock_manager).copy()
        self.assertEqual(copy.delivery_type, 'base_on_rule')
        self.assertEqual([copy.sudo()[name] for name in COD_FIELDS], [False, True, False, False])
        # yetkili kullanıcının kopyası bayrakları taşır
        copy = self.carrier.with_user(self.stock_cargo_manager).copy()
        self.assertEqual(copy.delivery_type, 'fixed')
        self.assertTrue(copy.sudo().cargo_cod_enabled)
        # yönetilen firmanın kopyası yönetilen firma açmaktır (O-1)
        with self.assertRaises(AccessError):
            self.carrier.with_user(self.stock_manager).copy()
