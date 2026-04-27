"""
Uğurlar Odoo Image Sync Agent
==============================
Windows bilgisayarında arka planda çalışarak belirtilen klasördeki
ürün görsellerini otomatik olarak Odoo'ya yükleyen hafif bir uygulama.

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
        # Ürün cache — aynı barkodu tekrar sorgulamak yerine cache'ten al
        self._product_cache = {}
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

        # product.image modeli gerçekten kullanılabilir mi kontrol et
        try:
            self._execute('product.image', 'fields_get', attributes=['string'])
            self.has_product_image = True
            _logger.info("product.image modeli mevcut — ek resimler destekleniyor.")
        except Exception:
            self.has_product_image = False
            _logger.info("product.image modeli yok — tüm resimler ana resim olarak yüklenecek.")

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
                fields=['id', 'name', 'product_tmpl_id', 'image_1920'],
            )
            if products:
                self._product_cache[barcode] = products[0]
                return products[0]
        return None

    def upload_image(self, filepath):
        """Tek bir görseli işle: barkod bul → ürüne ata."""
        filename = os.path.basename(filepath)
        name, ext = os.path.splitext(filename)
        separator = self.config['separator']
        main_index = self.config['main_image_index']

        # Barkod ve sıra ayrıştır
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

        if not barcode:
            _logger.warning("Barkod çıkarılamadı: %s", filename)
            return False, 'barkod_yok'

        # Ürünü bul
        product = self.find_product(barcode)
        if not product:
            _logger.warning("Ürün bulunamadı: %s (barkod: %s)", filename, barcode)
            return False, 'urun_yok'

        # Görseli sıkıştır ve oku
        img_b64 = compress_image(filepath)

        is_main = (str(order) == main_index)

        if is_main:
            # Mevcut resim kontrolü
            if product.get('image_1920') and not self.config['overwrite_existing']:
                _logger.info("Atlandı (mevcut var): %s → %s", filename, barcode)
                return True, 'atlandi'

            # Ana resmi güncelle — VARYANT bazlı (image_variant_1920)
            self._execute(
                'product.product', 'write',
                [product['id']],
                {'image_variant_1920': img_b64},
            )
            _logger.info("✅ ANA RESİM: %s → %s (%s)", filename, barcode, product['name'])
        else:
            # Ek resim ekle — VARYANT (barkod) bazlı
            if self.has_product_image:
                img_name = f'{barcode}{separator}{order}'

                # ── MÜKERRER KONTROLÜ ──
                # Aynı isimde resim varsa güncelle, yoksa oluştur
                existing = self._execute(
                    'product.image', 'search',
                    [
                        ('product_variant_id', '=', product['id']),
                        ('name', '=', img_name),
                    ],
                    limit=1,
                )

                if existing:
                    # Mevcut kaydı güncelle
                    self._execute(
                        'product.image', 'write',
                        existing,
                        {'image_1920': img_b64},
                    )
                    _logger.info("✅ EK RESİM #%d (güncellendi): %s → %s (%s)", order, filename, barcode, product['name'])
                else:
                    # Yeni kayıt oluştur
                    self._execute(
                        'product.image', 'create',
                        {
                            'product_variant_id': product['id'],
                            'name': img_name,
                            'image_1920': img_b64,
                        },
                    )
                    _logger.info("✅ EK RESİM #%d: %s → %s (%s)", order, filename, barcode, product['name'])
            else:
                self._execute(
                    'product.product', 'write',
                    [product['id']],
                    {'image_variant_1920': img_b64},
                )
                _logger.info("✅ RESİM #%d (ana olarak): %s → %s (%s)", order, filename, barcode, product['name'])

        return True, 'basarili'

    def process_folder(self):
        """Klasördeki tüm görselleri tarar ve işler."""
        watch = self.config['watch_folder']
        done = self.config['done_folder']
        error = self.config['error_folder']

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

        # Dosyaları barkod+sıra bazlı sırala (aynı barkodlar birlikte)
        files.sort(key=lambda p: os.path.basename(p))

        _logger.info("── %d yeni görsel bulundu ──", len(files))

        success = 0
        for fpath in files:
            try:
                ok, reason = self.upload_image(fpath)
                fname = os.path.basename(fpath)

                if ok and reason != 'urun_yok':
                    shutil.move(fpath, os.path.join(done, fname))
                    success += 1
                else:
                    shutil.move(fpath, os.path.join(error, fname))
            except Exception as e:
                _logger.error("Hata (%s): %s", os.path.basename(fpath), str(e))
                try:
                    shutil.move(fpath, os.path.join(error, os.path.basename(fpath)))
                except Exception:
                    pass

        _logger.info("── Tamamlandı: %d/%d başarılı ──", success, len(files))
        # Her tarama sonrasında cache temizle (yeni ürünler eklenmiş olabilir)
        self._product_cache.clear()
        return success


def main():
    """Ana döngü: klasörü belli aralıklarla tarar."""
    print("=" * 50)
    print("  Uğurlar Odoo Image Sync Agent")
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
