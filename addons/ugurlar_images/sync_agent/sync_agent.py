"""
Uğurlar Odoo Image Sync Agent
==============================
Windows bilgisayarında arka planda çalışarak belirtilen klasördeki
ürün görsellerini otomatik olarak Odoo'ya yükleyen hafif bir uygulama.

Özellikler:
  - Barkod bazlı görsel eşleştirme
  - Pillow ile resim sıkıştırma (hız optimizasyonu)
  - Mükerrer kayıt önleme (sil-ve-oluştur stratejisi)
  - Renk bazlı yayma (aynı renkteki tüm bedenlere otomatik kopyalama)

Kullanım:
  1. config.json dosyasını düzenleyin
  2. python sync_agent.py

Dosya adlandırma: BARKOD_SIRA.uzantı
  Örnek: 8691234560001_1.jpg  →  Ana resim
         8691234560001_2.jpg  →  Ek resim #2
"""

import base64
import io
import json
import logging
import os
import shutil
import sys
import time
import xmlrpc.client

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('sync_agent.log', encoding='utf-8'),
    ]
)
_logger = logging.getLogger('OdooImageSync')

# ── Desteklenen formatlar ──
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.tiff'}

# Resim sıkıştırma için max boyut (piksel)
MAX_IMAGE_SIZE = 1920

# ── Varsayılan config ──
DEFAULT_CONFIG = {
    "odoo_url": "https://odoo.ugurlar.com",
    "odoo_db": "ugurlar",
    "odoo_user": "admin",
    "odoo_password": "admin",
    "watch_folder": "./images",
    "done_folder": "./images/Gonderilenler",
    "error_folder": "./images/Hatalilar",
    "separator": "_",
    "main_image_index": "1",
    "match_field": "barcode",
    "overwrite_existing": True,
    "scan_interval_seconds": 3,
    "color_propagation": True,
    "color_attribute_name": "Renk",
}


def load_config(path='config.json'):
    """config.json dosyasını okur; yoksa varsayılan oluşturur."""
    if not os.path.exists(path):
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
        _logger.info("config.json oluşturuldu. Lütfen ayarları düzenleyin ve tekrar çalıştırın.")
        sys.exit(0)

    with open(path, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # Eksik anahtarları varsayılanlarla tamamla
    for key, val in DEFAULT_CONFIG.items():
        config.setdefault(key, val)

    return config


def compress_image(filepath):
    """Görseli sıkıştırarak base64 olarak döner. Pillow varsa optimize eder."""
    try:
        from PIL import Image

        img = Image.open(filepath)

        # EXIF rotasyonu uygula
        try:
            from PIL import ExifTags
            for orientation in ExifTags.TAGS.keys():
                if ExifTags.TAGS[orientation] == 'Orientation':
                    break
            exif = img._getexif()
            if exif and orientation in exif:
                rot = exif[orientation]
                if rot == 3:
                    img = img.rotate(180, expand=True)
                elif rot == 6:
                    img = img.rotate(270, expand=True)
                elif rot == 8:
                    img = img.rotate(90, expand=True)
        except Exception:
            pass

        # Boyutlandır (maks 1920px)
        w, h = img.size
        if w > MAX_IMAGE_SIZE or h > MAX_IMAGE_SIZE:
            img.thumbnail((MAX_IMAGE_SIZE, MAX_IMAGE_SIZE), Image.LANCZOS)

        # RGBA ise RGB'ye dönüştür
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')

        # JPEG olarak sıkıştır (kalite 85)
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=85, optimize=True)
        return base64.b64encode(buf.getvalue()).decode('ascii')

    except ImportError:
        # Pillow yoksa direkt oku
        with open(filepath, 'rb') as f:
            return base64.b64encode(f.read()).decode('ascii')


class OdooImageSync:
    """Odoo XML-RPC ile görsel yükleme motoru."""

    def __init__(self, config):
        self.config = config
        self.uid = None
        self.models = None
        self.has_product_image = False
        self._product_cache = {}
        # Renk kardeşleri cache — variant_id → [sibling_ids]
        self._sibling_cache = {}
        self._connect()

    def _connect(self):
        """Odoo'ya XML-RPC ile bağlan."""
        url = self.config['odoo_url'].rstrip('/')
        db = self.config['odoo_db']
        user = self.config['odoo_user']
        password = self.config['odoo_password']

        _logger.info("Odoo'ya bağlanılıyor: %s (DB: %s)", url, db)

        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        self.uid = common.authenticate(db, user, password, {})

        if not self.uid:
            raise Exception("Odoo bağlantısı başarısız! Kullanıcı adı/şifre kontrol edin.")

        self.models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')
        _logger.info("Odoo bağlantısı başarılı. UID: %d", self.uid)

        # product.image modeli kontrol
        try:
            self._execute('product.image', 'fields_get', attributes=['string'])
            self.has_product_image = True
            _logger.info("product.image modeli mevcut — ek resimler destekleniyor.")
        except Exception:
            self.has_product_image = False
            _logger.info("product.image modeli yok — tüm resimler ana resim olarak yüklenecek.")

        # Renk yayma durumu
        if self.config.get('color_propagation'):
            _logger.info("🎨 Renk yayma AKTİF — özellik adı: '%s'", self.config['color_attribute_name'])
        else:
            _logger.info("🎨 Renk yayma KAPALI")

    def _execute(self, model, method, *args, **kwargs):
        """Odoo XML-RPC execute_kw wrapper."""
        return self.models.execute_kw(
            self.config['odoo_db'],
            self.uid,
            self.config['odoo_password'],
            model, method,
            list(args),
            kwargs
        )

    def find_product(self, barcode):
        """Barkod ile ürün varyantını bul. Cache kullanır."""
        if barcode in self._product_cache:
            return self._product_cache[barcode]

        field = self.config['match_field']
        ids = self._execute(
            'product.product', 'search',
            [(field, '=', barcode)],
        )
        if ids:
            products = self._execute(
                'product.product', 'read',
                ids[:1],
                fields=['id', 'name', 'barcode', 'product_tmpl_id',
                        'image_1920', 'product_template_attribute_value_ids'],
            )
            if products:
                self._product_cache[barcode] = products[0]
                return products[0]
        return None

    def find_color_siblings(self, product):
        """
        Bir varyantın aynı renkteki kardeşlerini bul.

        Mantık:
        1. Varyantın product_template_attribute_value_ids'lerini oku
        2. 'Renk' özelliğine ait olanı bul
        3. Aynı template + aynı renk değerine sahip diğer varyantları döndür

        Returns: list of product dicts (kendisi HARİÇ)
        """
        variant_id = product['id']

        # Cache kontrolü
        if variant_id in self._sibling_cache:
            return self._sibling_cache[variant_id]

        color_attr_name = self.config.get('color_attribute_name', 'Renk')
        tmpl_id = product['product_tmpl_id'][0]
        ptav_ids = product.get('product_template_attribute_value_ids', [])

        if not ptav_ids:
            self._sibling_cache[variant_id] = []
            return []

        # PTAV kayıtlarını oku — hangi özellik (attribute) hangi değer
        ptavs = self._execute(
            'product.template.attribute.value', 'read',
            ptav_ids,
            fields=['id', 'attribute_id', 'name'],
        )

        # 'Renk' özelliğine ait PTAV'ı bul
        color_ptav = None
        for ptav in ptavs:
            attr_name = ptav['attribute_id'][1] if isinstance(ptav['attribute_id'], list) else ''
            if attr_name.lower() in (color_attr_name.lower(), 'color', 'colour'):
                color_ptav = ptav
                break

        if not color_ptav:
            _logger.debug("Bu varyant için '%s' özelliği bulunamadı: %s", color_attr_name, product['name'])
            self._sibling_cache[variant_id] = []
            return []

        # Aynı template + aynı renk PTAV'ına sahip varyantları bul
        sibling_ids = self._execute(
            'product.product', 'search',
            [
                ('product_tmpl_id', '=', tmpl_id),
                ('product_template_attribute_value_ids', 'in', [color_ptav['id']]),
                ('id', '!=', variant_id),
            ],
        )

        siblings = []
        if sibling_ids:
            siblings = self._execute(
                'product.product', 'read',
                sibling_ids,
                fields=['id', 'name', 'barcode', 'product_tmpl_id'],
            )

        self._sibling_cache[variant_id] = siblings
        if siblings:
            names = [s.get('barcode') or s['name'] for s in siblings]
            _logger.info("🎨 %s renk kardeşleri (%s): %s",
                         product.get('barcode') or product['name'],
                         color_ptav['name'],
                         ', '.join(names))

        return siblings

    def _clean_variant_images(self, variant_id, tmpl_id):
        """Bir varyantın tüm eski ek resimlerini sil."""
        if not self.has_product_image:
            return 0

        old_images = self._execute(
            'product.image', 'search',
            [
                '|',
                ('product_variant_id', '=', variant_id),
                ('product_tmpl_id', '=', tmpl_id),
            ],
        )
        if old_images:
            self._execute('product.image', 'unlink', old_images)
            return len(old_images)
        return 0

    def _upload_to_variant(self, variant_id, barcode, img_b64, order, separator):
        """Tek bir varyanta ana veya ek resim yükle."""
        main_index = self.config['main_image_index']
        is_main = (str(order) == main_index)

        if is_main:
            self._execute(
                'product.product', 'write',
                [variant_id],
                {'image_variant_1920': img_b64},
            )
        else:
            if self.has_product_image:
                img_name = f'{barcode}{separator}{order}'
                self._execute(
                    'product.image', 'create',
                    {
                        'product_variant_id': variant_id,
                        'name': img_name,
                        'image_1920': img_b64,
                    },
                )
            else:
                self._execute(
                    'product.product', 'write',
                    [variant_id],
                    {'image_variant_1920': img_b64},
                )

    def process_folder(self):
        """Klasördeki tüm görselleri tarar ve işler."""
        watch = self.config['watch_folder']
        done = self.config['done_folder']
        error = self.config['error_folder']
        separator = self.config['separator']
        main_index = self.config['main_image_index']
        color_propagation = self.config.get('color_propagation', False)

        # Klasörleri oluştur
        os.makedirs(watch, exist_ok=True)
        os.makedirs(done, exist_ok=True)
        os.makedirs(error, exist_ok=True)

        files = []
        for f in os.listdir(watch):
            fpath = os.path.join(watch, f)
            if not os.path.isfile(fpath):
                continue
            _, ext = os.path.splitext(f)
            if ext.lower() in ALLOWED_EXTENSIONS:
                files.append(fpath)

        if not files:
            return 0

        # Dosyaları barkod bazlı grupla
        barcode_groups = {}
        for fpath in files:
            fname = os.path.basename(fpath)
            name, ext = os.path.splitext(fname)
            parts = name.rsplit(separator, 1)
            if len(parts) == 2:
                barcode = parts[0].strip()
                try:
                    order = int(parts[1].strip())
                except ValueError:
                    barcode = name
                    order = int(main_index)
            else:
                barcode = name
                order = int(main_index)

            if barcode:
                barcode_groups.setdefault(barcode, []).append((order, fpath))

        _logger.info("── %d görsel bulundu (%d barkod) ──", len(files), len(barcode_groups))

        success = 0
        for barcode, items in barcode_groups.items():
            items.sort(key=lambda x: x[0])

            # Ürünü bul
            product = self.find_product(barcode)
            if not product:
                _logger.warning("Ürün bulunamadı (barkod: %s) — %d dosya atlanıyor", barcode, len(items))
                for _, fpath in items:
                    try:
                        shutil.move(fpath, os.path.join(error, os.path.basename(fpath)))
                    except Exception:
                        pass
                continue

            tmpl_id = product['product_tmpl_id'][0]

            # ── Hedef varyantları belirle ──
            target_variants = [product]  # en azından kendisi

            if color_propagation:
                siblings = self.find_color_siblings(product)
                for sib in siblings:
                    target_variants.append(sib)

            # ── TÜM HEDEF VARYANTLARIN ESKİ RESİMLERİNİ SİL ──
            for tv in target_variants:
                deleted = self._clean_variant_images(tv['id'], tmpl_id)
                if deleted > 0:
                    _logger.info("🗑️ %d eski ek resim silindi: %s",
                                 deleted, tv.get('barcode') or tv['name'])

            # ── DOSYALARI İŞLE ──
            # Önce tüm dosyaları oku ve sıkıştır (1 kez oku, N varyanta yaz)
            image_data = []  # [(order, fname, fpath, img_b64), ...]
            for order, fpath in items:
                fname = os.path.basename(fpath)
                try:
                    img_b64 = compress_image(fpath)
                    image_data.append((order, fname, fpath, img_b64))
                except Exception as e:
                    _logger.error("Sıkıştırma hatası (%s): %s", fname, str(e))
                    try:
                        shutil.move(fpath, os.path.join(error, fname))
                    except Exception:
                        pass

            # Her hedef varyanta yükle
            for tv in target_variants:
                tv_barcode = tv.get('barcode') or tv['name']
                tv_id = tv['id']
                is_self = (tv_id == product['id'])

                for order, fname, fpath, img_b64 in image_data:
                    try:
                        self._upload_to_variant(tv_id, tv_barcode, img_b64, order, separator)

                        is_main = (str(order) == main_index)
                        if is_self:
                            label = "ANA RESİM" if is_main else f"EK RESİM #{order}"
                            _logger.info("✅ %s: %s → %s", label, fname, tv_barcode)
                        else:
                            label = "ANA" if is_main else f"EK #{order}"
                            _logger.info("  🎨 %s → %s (renk kardeşi)", label, tv_barcode)
                    except Exception as e:
                        _logger.error("Yükleme hatası (%s → %s): %s", fname, tv_barcode, str(e))

            # Dosyaları taşı
            for order, fname, fpath, img_b64 in image_data:
                try:
                    shutil.move(fpath, os.path.join(done, fname))
                    success += 1
                except Exception:
                    pass

        _logger.info("── Tamamlandı: %d/%d başarılı ──", success, len(files))
        self._product_cache.clear()
        self._sibling_cache.clear()
        return success


def main():
    """Ana döngü: klasörü belli aralıklarla tarar."""
    print("=" * 50)
    print("  Uğurlar Odoo Image Sync Agent v2.0")
    print("  🎨 Renk bazlı yayma destekli")
    print("  Çıkmak için Ctrl+C")
    print("=" * 50)

    config = load_config()
    agent = OdooImageSync(config)
    interval = config['scan_interval_seconds']

    _logger.info("Klasör izleniyor: %s (her %d saniyede bir)", config['watch_folder'], interval)

    try:
        while True:
            agent.process_folder()
            time.sleep(interval)
    except KeyboardInterrupt:
        _logger.info("Agent durduruldu.")


if __name__ == '__main__':
    main()
