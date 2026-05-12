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
import sqlite3
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
        # SQLite cache başlat — her dosya anında diske yazılır (Odoo gerekmez)
        self._init_db()
        # Odoo bağlantısı — başarısız olursa agent bekler
        try:
            self._connect()
        except Exception as e:
            _logger.warning("Odoo bağlantısı başarısız, tekrar denenecek: %s", e)

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

        # ── Odoo'dan dinamik ayarları çek ──
        self._sync_odoo_settings()

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

    def _sync_odoo_settings(self):
        """Odoo Ayarlar'dan dinamik config değerlerini çeker (klasör yolu vb.)."""
        # Docker modunda mıyız? /data/images varsa Docker volume mount aktif
        is_docker = os.path.isdir('/data/images')

        _PARAM_MAP = {
            'ugurlar_images.image_watch_folder': 'watch_folder',
            'ugurlar_images.image_separator': '_separator_key',
            'ugurlar_images.main_image_index': '_main_index_key',
            'ugurlar_images.image_match_field': 'match_field',
            'ugurlar_images.image_overwrite': '_overwrite_str',
        }
        _SEP_MAP = {'underscore': '_', 'dash': '-', 'dot': '.'}
        _IDX_MAP = {'idx0': '0', 'idx1': '1'}

        try:
            for param_key, config_key in _PARAM_MAP.items():
                val = self._execute(
                    'ir.config_parameter', 'get_param',
                    param_key,
                )
                if val:
                    if config_key == 'watch_folder':
                        # Docker modunda klasör yolunu override ETME
                        # Docker volume mount zaten doğru yolu bağlıyor
                        if is_docker:
                            _logger.info("📁 Docker modu — Odoo yolu: %s (volume mount kullanılıyor)", val)
                        else:
                            old = self.config.get('watch_folder', '')
                            self.config['watch_folder'] = val
                            if old != val:
                                self.config['done_folder'] = os.path.join(val, 'Gonderilenler')
                                self.config['error_folder'] = os.path.join(val, 'Hatalilar')
                                _logger.info("📁 Klasör yolu güncellendi: %s → %s", old, val)
                    elif config_key == '_separator_key':
                        self.config['separator'] = _SEP_MAP.get(val, self.config['separator'])
                    elif config_key == '_main_index_key':
                        self.config['main_image_index'] = _IDX_MAP.get(val, self.config['main_image_index'])
                    elif config_key == 'match_field':
                        self.config['match_field'] = val
                    elif config_key == '_overwrite_str':
                        self.config['overwrite_existing'] = val.lower() in ('true', '1', 'yes')

            _logger.info("📁 Aktif klasör: %s", self.config['watch_folder'])
        except Exception as e:
            _logger.warning("Odoo'dan ayarlar çekilemedi (lokal config kullanılıyor): %s", e)

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

    def _upload_to_variant(self, variant_id, barcode, img_b64, order, separator, tmpl_id=None):
        """Tek bir varyanta ana veya ek resim yükle."""
        main_index = self.config['main_image_index']
        is_main = (str(order) == main_index)

        if is_main:
            self._execute(
                'product.product', 'write',
                [variant_id],
                {'image_variant_1920': img_b64},
            )

            # ── TEMPLATE KAPAK GÖRSELİ ──
            # _compute_image_1920 override sayesinde bu artık güvenli:
            # çoklu varyantlarda template resmi varyantlara sızmaz.
            if tmpl_id:
                tmpl_data = self._execute(
                    'product.template', 'read',
                    [tmpl_id],
                    fields=['image_1920'],
                )
                if tmpl_data and not tmpl_data[0].get('image_1920'):
                    self._execute(
                        'product.template', 'write',
                        [tmpl_id],
                        {'image_1920': img_b64},
                    )
                    _logger.info("🖼️ Template kapak görseli ayarlandı (tmpl_id=%d)", tmpl_id)
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

    # ═══════════════════════════════════════════════════════════════
    # SQLite CACHE — her dosya anında diske yazılır, crash-safe
    # ═══════════════════════════════════════════════════════════════

    def _db_path(self):
        """SQLite veritabanı yolunu döner (agent'ın yanında)."""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed_cache.db')

    def _init_db(self):
        """SQLite veritabanını başlat ve tabloyu oluştur."""
        db_path = self._db_path()
        self._db = sqlite3.connect(db_path)
        self._db.execute('PRAGMA journal_mode=WAL')   # Yazma sırasında okuma yapılabilsin
        self._db.execute('PRAGMA synchronous=NORMAL') # Performans vs güvenlik dengesi
        self._db.execute('''
            CREATE TABLE IF NOT EXISTS processed_files (
                filename TEXT PRIMARY KEY,
                file_size INTEGER,
                file_mtime TEXT,
                barcode TEXT,
                state TEXT DEFAULT 'done',
                product_id INTEGER,
                tmpl_id INTEGER,
                image_type TEXT,
                image_order INTEGER,
                error_msg TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        self._db.commit()

        # Eski JSON cache varsa migrate et
        self._migrate_json_cache()

        count = self._db.execute('SELECT COUNT(*) FROM processed_files').fetchone()[0]
        _logger.info("📦 SQLite cache hazır: %d dosya kaydı (%s)", count, db_path)

    def _migrate_json_cache(self):
        """Eski processed_cache.json varsa SQLite'a aktar ve sil."""
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed_cache.json')
        if not os.path.exists(json_path):
            return
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if not data:
                return
            migrated = 0
            for fname, entry in data.items():
                try:
                    self._db.execute(
                        'INSERT OR IGNORE INTO processed_files (filename, file_size, file_mtime, barcode, state) VALUES (?, ?, ?, ?, ?)',
                        (fname, entry.get('size', 0), entry.get('mtime', ''), entry.get('barcode', ''), entry.get('state', 'done'))
                    )
                    migrated += 1
                except Exception:
                    pass
            self._db.commit()
            # Eski dosyayı yedekle
            os.rename(json_path, json_path + '.migrated')
            _logger.info("📦 JSON cache → SQLite migrate edildi: %d kayıt", migrated)
        except Exception as e:
            _logger.warning("JSON cache migration hatası: %s", e)

    # ═══════════════════════════════════════════════════════════════
    # DOSYA META & KONTROL
    # ═══════════════════════════════════════════════════════════════

    def _get_file_meta(self, fpath):
        """Dosyanın boyut ve değişiklik tarihini döner."""
        try:
            stat = os.stat(fpath)
            return int(stat.st_size), str(int(stat.st_mtime))
        except OSError:
            return 0, ''

    def _is_file_processed(self, fname, file_size, file_mtime):
        """SQLite'tan dosyanın işlenip işlenmediğini kontrol eder.
        
        Network çağrısı YAPMAZ — sadece lokal SQLite'a bakar.
        Dosya boyutu veya tarihi değişmişse → tekrar işlenecek.
        """
        row = self._db.execute(
            'SELECT file_size, file_mtime, state FROM processed_files WHERE filename = ?',
            (fname,)
        ).fetchone()

        if not row:
            return False

        db_size, db_mtime, db_state = row
        if db_size != file_size or db_mtime != file_mtime:
            return False

        return db_state == 'done'

    # ═══════════════════════════════════════════════════════════════
    # KAYIT — Lokal cache (hızlı) + Odoo DB (raporlama)
    # ═══════════════════════════════════════════════════════════════

    def _record_success(self, filename, barcode, file_size, file_mtime,
                        product_id, tmpl_id, image_type, order,
                        color_propagated=False, sibling_count=0):
        """Başarılı dosyayı SQLite'a ANINDA kaydet + Odoo'ya best-effort."""
        # ── 1. SQLite (anında diske, crash-safe) ──
        self._db.execute(
            '''INSERT OR REPLACE INTO processed_files
               (filename, file_size, file_mtime, barcode, state, product_id, tmpl_id, image_type, image_order)
               VALUES (?, ?, ?, ?, 'done', ?, ?, ?, ?)''',
            (filename, file_size, file_mtime, barcode, product_id, tmpl_id, image_type, order)
        )
        self._db.commit()  # Her dosya anında diske!

        # ── 2. Odoo DB (best-effort, hata olursa SQLite yeter) ──
        try:
            self._execute(
                'ugurlar.image.sync.file', 'mark_processed',
                filename, barcode, file_size, file_mtime,
                product_id=product_id,
                tmpl_id=tmpl_id,
                image_type=image_type,
                image_order=order,
                color_propagated=color_propagated,
                sibling_count=sibling_count,
            )
        except Exception as e:
            _logger.debug("Odoo kayıt yazılamadı (%s) — SQLite yeterli: %s", filename, e)

    def _record_error(self, filename, barcode, file_size, file_mtime, error_msg):
        """Hatalı dosyayı SQLite'a ANINDA kaydet + Odoo'ya best-effort."""
        # ── 1. SQLite ──
        self._db.execute(
            '''INSERT OR REPLACE INTO processed_files
               (filename, file_size, file_mtime, barcode, state, error_msg)
               VALUES (?, ?, ?, ?, 'error', ?)''',
            (filename, file_size, file_mtime, barcode, error_msg)
        )
        self._db.commit()

        # ── 2. Odoo DB (best-effort) ──
        try:
            self._execute(
                'ugurlar.image.sync.file', 'mark_error',
                filename, barcode, file_size, file_mtime, error_msg,
            )
        except Exception as e:
            _logger.debug("Odoo hata kaydı yazılamadı (%s): %s", filename, e)

    # ═══════════════════════════════════════════════════════════════
    # ANA İŞLEM DÖNGÜSÜ
    # ═══════════════════════════════════════════════════════════════

    def process_folder(self):
        """Klasördeki tüm görselleri tarar ve işler.
        
        HİBRİT MOD:
          - SQLite cache (processed_cache.db) → hızlı kontrol, network yok
          - Odoo DB (ugurlar.image.sync.file) → raporlama, merkezi takip
        
        Dosyalar yerinde bırakılır (taşınmaz).
        Sadece yeni veya değişmiş dosyalar işlenir.
        Hatalı dosyalar Hatalilar klasörüne taşınır.
        """
        # Odoo bağlantısı yoksa yeniden bağlanmayı dene
        if not self.uid:
            try:
                self._connect()
            except Exception:
                _logger.debug("Odoo henüz hazır değil, sonraki döngüde denenecek")
                return 0

        watch = self.config['watch_folder']
        error_dir = self.config['error_folder']
        separator = self.config['separator']
        main_index = self.config['main_image_index']
        color_propagation = self.config.get('color_propagation', False)

        # Ağ sürücüsü erişim kontrolü
        if not os.path.exists(watch):
            try:
                os.makedirs(watch, exist_ok=True)
            except OSError as e:
                _logger.warning("📁 Klasöre erişilemiyor: %s — %s (ağ sürücüsü bağlı mı?)", watch, e)
                return 0

        # Hatalılar klasörünü oluştur
        os.makedirs(error_dir, exist_ok=True)

        # ── Klasördeki görselleri tara ──
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

        # ── Yeni/değişmiş dosyaları filtrele (LOKAL CACHE — 0ms) ──
        new_files = []
        skipped = 0
        for fpath in files:
            fname = os.path.basename(fpath)
            file_size, file_mtime = self._get_file_meta(fpath)

            if self._is_file_processed(fname, file_size, file_mtime):
                skipped += 1
                continue

            # Cache'de var ama değişmiş?
            existing = self._db.execute(
                'SELECT 1 FROM processed_files WHERE filename = ?', (fname,)
            ).fetchone()
            if existing:
                _logger.info("🔄 Dosya değişmiş, tekrar işlenecek: %s", fname)

            new_files.append(fpath)

        if not new_files:
            return 0

        if skipped > 0:
            _logger.debug("⏭️ %d dosya zaten işlenmiş, atlandı", skipped)

        # ── Dosyaları barkod bazlı grupla ──
        barcode_groups = {}
        for fpath in new_files:
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

        _logger.info("── %d yeni görsel bulundu (%d barkod) ──", len(new_files), len(barcode_groups))

        success = 0
        for barcode, items in barcode_groups.items():
            items.sort(key=lambda x: x[0])

            # Ürünü bul
            product = self.find_product(barcode)
            if not product:
                _logger.warning("Ürün bulunamadı (barkod: %s) — %d dosya hatalılar'a taşınıyor", barcode, len(items))
                for _, fpath in items:
                    fname = os.path.basename(fpath)
                    file_size, file_mtime = self._get_file_meta(fpath)
                    error_msg = f"Ürün bulunamadı (barkod: {barcode})"
                    self._record_error(fname, barcode, file_size, file_mtime, error_msg)
                    try:
                        shutil.move(fpath, os.path.join(error_dir, fname))
                    except Exception:
                        pass
                continue

            tmpl_id = product['product_tmpl_id'][0]

            # ── Hedef varyantları belirle ──
            target_variants = [product]

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
            image_data = []
            for order, fpath in items:
                fname = os.path.basename(fpath)
                file_size, file_mtime = self._get_file_meta(fpath)
                try:
                    img_b64 = compress_image(fpath)
                    image_data.append((order, fname, fpath, img_b64, file_size, file_mtime))
                except Exception as e:
                    _logger.error("Sıkıştırma hatası (%s): %s", fname, str(e))
                    self._record_error(fname, barcode, file_size, file_mtime, str(e))
                    try:
                        shutil.move(fpath, os.path.join(error_dir, fname))
                    except Exception:
                        pass

            # Her hedef varyanta yükle
            sibling_count = len(target_variants) - 1
            for tv in target_variants:
                tv_barcode = tv.get('barcode') or tv['name']
                tv_id = tv['id']
                is_self = (tv_id == product['id'])

                for order, fname, fpath, img_b64, file_size, file_mtime in image_data:
                    try:
                        self._upload_to_variant(tv_id, tv_barcode, img_b64, order, separator, tmpl_id=tmpl_id)

                        is_main = (str(order) == main_index)
                        if is_self:
                            label = "ANA RESİM" if is_main else f"EK RESİM #{order}"
                            _logger.info("✅ %s: %s → %s", label, fname, tv_barcode)
                        else:
                            label = "ANA" if is_main else f"EK #{order}"
                            _logger.info("  🎨 %s → %s (renk kardeşi)", label, tv_barcode)
                    except Exception as e:
                        _logger.error("Yükleme hatası (%s → %s): %s", fname, tv_barcode, str(e))

            # ── Başarılı dosyaları kaydet (lokal + Odoo) ──
            for order, fname, fpath, img_b64, file_size, file_mtime in image_data:
                is_main = (str(order) == main_index)
                image_type = 'main' if is_main else 'extra'
                self._record_success(
                    fname, barcode, file_size, file_mtime,
                    product_id=product['id'],
                    tmpl_id=tmpl_id,
                    image_type=image_type,
                    order=order,
                    color_propagated=color_propagation and sibling_count > 0,
                    sibling_count=sibling_count,
                )
                success += 1

        # SQLite zaten her dosyada commit ediyor, ekstra save gerekmez
        _logger.info("── Tamamlandı: %d/%d başarılı ──", success, len(new_files))
        self._product_cache.clear()
        self._sibling_cache.clear()
        return success


def main():
    """Ana döngü: klasörü belli aralıklarla tarar."""
    print("=" * 50)
    print("  Ugurlar Odoo Image Sync Agent v3.2")
    print("  Renk bazli yayma destekli")
    print("  SQLite cache - crash-safe, kaldigi yerden devam")
    print("  Cikmak icin Ctrl+C")
    print("=" * 50)

    config = load_config()
    agent = OdooImageSync(config)
    interval = config['scan_interval_seconds']

    _logger.info("Klasör izleniyor: %s (her %d saniyede bir)", config['watch_folder'], interval)

    try:
        while True:
            try:
                agent.process_folder()
            except KeyboardInterrupt:
                raise
            except Exception as e:
                _logger.error("⚠️ Tarama hatası (kaldığı yerden devam edecek): %s", e)
                _logger.info("🔄 30 saniye bekleyip tekrar denenecek...")
                time.sleep(30)
                # Odoo bağlantısını yenile
                try:
                    agent._connect()
                    _logger.info("✅ Odoo bağlantısı yenilendi")
                except Exception:
                    _logger.warning("Odoo bağlantısı henüz yenilenemiyor, beklenecek...")
                continue
            time.sleep(interval)
    except KeyboardInterrupt:
        agent._db.close()
        _logger.info("Agent durduruldu. SQLite kapatıldı.")


if __name__ == '__main__':
    main()
