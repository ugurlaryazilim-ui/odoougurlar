from odoo import fields, models, tools


class TrendyolTransactionCheck(models.Model):
    """İşlem Kontrol: finansal işlemlerin sipariş bazında tek satırda özeti (SQL görünümü, salt okunur).

    Her satır bir mağaza + sipariş numarası; satış, indirim, komisyon ve tüm kesintiler ayrı sütunlarda.
    Toplu (sipariş numarasız) faturalar ve ödeme kayıtları dahil edilmez — onların sipariş payları
    'Hizmet Bedeli Dağıtımı' satırları olarak zaten siparişe yazılıdır.
    """
    _name = 'trendyol.transaction.check'
    _description = 'Trendyol İşlem Kontrol'
    _auto = False
    _order = 'order_date desc, order_number desc'
    _rec_name = 'order_number'

    order_date = fields.Datetime(string='Sipariş Tarihi', readonly=True)
    delivery_date = fields.Datetime(string='Teslim Tarihi', readonly=True,
                                    help='Satış kaydının oluştuğu tarih (Trendyol satışı teslimatta kaydeder)')
    due_date = fields.Datetime(string='Vade Tarihi', readonly=True, help='Satış kaydının ödeme (vade) tarihi')
    order_number = fields.Char(string='Sipariş No', readonly=True)
    store_id = fields.Many2one('trendyol.store', string='Mağaza', readonly=True)
    order_id = fields.Many2one('trendyol.order', string='Trendyol Sipariş', readonly=True)
    sale_amount = fields.Float(string='Satış', digits=(12, 2), readonly=True)
    return_amount = fields.Float(string='İade', digits=(12, 2), readonly=True)
    discount_amount = fields.Float(string='İndirim', digits=(12, 2), readonly=True)
    commission_amount = fields.Float(string='Komisyon', digits=(12, 2), readonly=True)
    platform_fee = fields.Float(string='Platform Hizmet Bedeli', digits=(12, 2), readonly=True)
    shipping_cost = fields.Float(string='Gönderi Kargo Tutarı', digits=(12, 2), readonly=True)
    return_cargo_cost = fields.Float(string='İade Kargo Tutarı', digits=(12, 2), readonly=True)
    penalty_amount = fields.Float(string='Ceza Tutarı', digits=(12, 2), readonly=True)
    commission_rate = fields.Float(string='Komisyon Oranı (%)', digits=(5, 2), readonly=True)
    international_fee = fields.Float(string='Uluslararası Hizmet Bedeli', digits=(12, 2), readonly=True)
    stoppage_amount = fields.Float(string='E-Ticaret Stopajı', digits=(12, 2), readonly=True)
    barcode = fields.Char(string='Barkod', readonly=True)
    credit = fields.Float(string='Alacak', digits=(12, 2), readonly=True)
    debt = fields.Float(string='Borç', digits=(12, 2), readonly=True)
    net_amount = fields.Float(string='Net Tutar', digits=(12, 2), readonly=True,
                              help='Paneldeki "Net Tutar": Satış − İade − İndirim − Komisyon − Uluslararası Hizmet Bedeli')
    net_order_amount = fields.Float(
        string='Net Sipariş Tutarı', digits=(12, 2), readonly=True,
        help='Paneldeki "Net Sipariş Tutarı": Net Tutar − Platform Hizmet Bedeli − Gönderi Kargo − İade Kargo − Ceza')
    seller_revenue = fields.Float(string='Hakedişe Etki', digits=(12, 2), readonly=True,
                                  help='Panelde "Net Sipariş Tutarı" karşılığı (Finansal İşlemler → Hakedişe Etki toplamı)')
    payment_order_id = fields.Char(string='Hakediş Ödeme No', readonly=True)
    receipt_id = fields.Char(string='Dekont No', readonly=True)
    affiliate = fields.Char(string='Affiliate', readonly=True)
    is_paid = fields.Boolean(string='Ödendi', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        # Panel "Net Tutar": satış − iade − indirim/kupon (iptaller dahil) − komisyon − uluslararası bedel
        net = """(SUM(CASE WHEN s.transaction_type = 'sale' THEN s.credit - s.debt
                          WHEN s.transaction_type = 'return' THEN s.credit - s.debt
                          WHEN s.transaction_type IN ('discount', 'discount_cancel', 'coupon', 'coupon_cancel',
                                                      'international_fee') THEN s.credit - s.debt
                          ELSE 0 END)
                  - SUM(COALESCE(s.signed_commission, 0)))"""
        self.env.cr.execute(f"""
            CREATE OR REPLACE VIEW {self._table} AS (
                SELECT
                    MIN(s.id) AS id,
                    s.store_id,
                    s.order_number,
                    MIN(s.order_id) AS order_id,
                    COALESCE(MIN(o.order_date),
                             MIN(s.transaction_date) FILTER (WHERE s.transaction_type = 'sale'),
                             MIN(s.transaction_date)) AS order_date,
                    MIN(s.transaction_date) FILTER (WHERE s.transaction_type = 'sale') AS delivery_date,
                    MAX(s.payment_date) FILTER (WHERE s.transaction_type = 'sale') AS due_date,
                    SUM(CASE WHEN s.transaction_type = 'sale' THEN s.credit - s.debt ELSE 0 END) AS sale_amount,
                    SUM(CASE WHEN s.transaction_type = 'return' THEN s.debt - s.credit ELSE 0 END) AS return_amount,
                    SUM(CASE WHEN s.transaction_type IN ('discount', 'discount_cancel', 'coupon', 'coupon_cancel')
                             THEN s.debt - s.credit ELSE 0 END) AS discount_amount,
                    SUM(COALESCE(s.signed_commission, 0)) AS commission_amount,
                    SUM(CASE WHEN s.transaction_type = 'platform_fee' THEN s.debt - s.credit ELSE 0 END) AS platform_fee,
                    SUM(CASE WHEN s.transaction_type = 'shipping_cargo' THEN s.debt - s.credit ELSE 0 END) AS shipping_cost,
                    SUM(CASE WHEN s.transaction_type = 'return_cargo' THEN s.debt - s.credit ELSE 0 END) AS return_cargo_cost,
                    SUM(CASE WHEN s.transaction_type = 'penalty' THEN s.debt - s.credit ELSE 0 END) AS penalty_amount,
                    SUM(CASE WHEN s.transaction_type = 'international_fee' THEN s.debt - s.credit ELSE 0 END) AS international_fee,
                    SUM(CASE WHEN s.transaction_type = 'stoppage' THEN s.debt - s.credit ELSE 0 END) AS stoppage_amount,
                    MAX(s.commission_rate) AS commission_rate,
                    STRING_AGG(DISTINCT NULLIF(s.barcode, ''), ', ') AS barcode,
                    SUM(COALESCE(s.credit, 0)) AS credit,
                    SUM(COALESCE(s.debt, 0)) AS debt,
                    {net} AS net_amount,
                    {net} - SUM(CASE WHEN s.transaction_type IN ('platform_fee', 'shipping_cargo', 'return_cargo', 'penalty')
                                     THEN s.debt - s.credit ELSE 0 END) AS net_order_amount,
                    SUM(COALESCE(s.signed_seller_revenue, 0)) AS seller_revenue,
                    STRING_AGG(DISTINCT NULLIF(s.payment_order_id, ''), ', ') AS payment_order_id,
                    STRING_AGG(DISTINCT NULLIF(s.receipt_id, ''), ', ') AS receipt_id,
                    STRING_AGG(DISTINCT NULLIF(s.affiliate, ''), ', ') AS affiliate,
                    BOOL_AND(COALESCE(s.payment_order_id, '') <> '')
                        FILTER (WHERE s.transaction_type = 'sale') AS is_paid
                FROM trendyol_settlement s
                LEFT JOIN trendyol_order o ON o.id = s.order_id
                WHERE COALESCE(s.order_number, '') <> ''
                  AND COALESCE(s.transaction_type, '') <> 'payment'
                GROUP BY s.store_id, s.order_number
            )
        """)
