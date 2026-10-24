# -*- coding: utf-8 -*-
"""Birim testleri için taban (kabul tabanı ``kabul_taban.py`` test-mühendisine aittir, değiştirilmez).

``CargoTestCase``: kabul tabanının ağ engeli, kullanıcılar ve firma kurulumunu devralır; ``cargo.area`` /
``cargo.shipment`` gerektirmez (G1 testleri bunlar gelmeden de koşar), sahte sağlayıcıyı kendisi yamalar.
"""
from unittest.mock import patch

from .kabul_taban import CargoKabulCase, FakeProvider, NetBlock, make_label_png  # noqa: F401


class CargoTestCase(CargoKabulCase):
    REQUIRES_MODELS = ()
    # NEDEN: kabul tabanının FakeProvider'ı kayıt (cargo.shipment) bekler; birim testleri
    # sağlayıcı metodunu stub_provider() ile kendisi ekler.
    PROVIDER_TYPES = ()

    def stub_provider(self, delivery_type='fixed', ops=('send', 'cancel', 'find'), result=None):
        """``<tip>_cargo_<op>`` metotlarını (create=True) ekler; ``calls`` listesine (op, args) yazar."""
        calls = []
        carrier_cls = type(self.env['delivery.carrier'])
        for op in ops:
            def method(carrier, *args, _op=op, **kwargs):
                calls.append((_op, args))
                return dict(result or {'status': 'ok'})
            patcher = patch.object(carrier_cls, '%s_cargo_%s' % (delivery_type, op), method, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)
        return calls
