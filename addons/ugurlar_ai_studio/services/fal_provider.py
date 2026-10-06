# fal.ai provider implementation.
#
# fal_client SDK kullanir - kuyruk destekli, otomatik retry,
# timeout yonetimi ve yapisal hata ayristirma entegrasyonu ile.

import base64
import logging
import threading
import time


from .ai_provider_base import AIProviderBase

_logger = logging.getLogger(__name__)

# fal_client her kuyruk durum sorgusunu (saniyede birkaç kez) httpx INFO satırı olarak
# yazıyor ve log'u boğuyordu; uyarı/hatalar görünmeye devam eder
logging.getLogger('httpx').setLevel(logging.WARNING)

try:
    import fal_client
except ImportError:
    fal_client = None
    _logger.warning(
        'fal-client kurulu degil. AI ozellikleri calismayacak. '
        'Kurulum: pip install fal-client'
    )


class FalQueueTimeout(Exception):
    """İş fal kuyruğunda sürerken bekleme süresi doldu (iş İPTAL EDİLMEDİ).

    Sınıf adında 'Timeout' geçer: session._is_client_timeout bunu tanır ve sonucu
    cron'un request_id ile almasına bırakır.
    """

    def __init__(self, request_id, timeout):
        super().__init__('fal isteği %ss içinde bitmedi (request_id=%s)' % (timeout, request_id))
        self.request_id = request_id


class FalProvider(AIProviderBase):
    # fal.ai FASHN v1.6 implementasyonu.
    #
    # Tum API cagrilari fal_client.subscribe() ile yapilir:
    # - Kuyruk destekli (otomatik retry, 10 kez)
    # - client_timeout ile zaman asimi kontrolu
    # - on_queue_update ile ilerleme takibi

    ENDPOINTS = {
        'tryon_fashn': 'fal-ai/fashn/tryon/v1.6',
        'bg_remove': 'fal-ai/birefnet',
        'flux_schnell': 'fal-ai/flux/schnell',
        'nano_banana': 'fal-ai/nano-banana-2/edit',
        'seedream': 'bytedance/seedream/v5/pro/edit',
        # v4 Edit seed alır ve döndürür: ön görünüm seed'i arka/yan çekimlere aktarılabilir
        'seedream_v4': 'fal-ai/bytedance/seedream/v4/edit',
        'any_llm': 'fal-ai/any-llm',
    }

    # Endpoint basina tahmini maliyet (USD)
    ESTIMATED_COSTS = {
        'fal-ai/fashn/tryon/v1.6': 0.075,
        'fal-ai/birefnet': 0.002,
        'fal-ai/flux/schnell': 0.003,
        'fal-ai/flux-pro/v1.1': 0.05,
        'fal-ai/nano-banana-2/edit': 0.04,
        'bytedance/seedream/v5/pro/edit': 0.135,
        'fal-ai/bytedance/seedream/v4/edit': 0.03,  # fal liste fiyatı (görsel başına) — faturayla teyit edilmeli
        'fal-ai/any-llm': 0.001,
        'fal-ai/flux-kontext/dev': 0.025,
    }

    # Seedream çıktı boyutları (2:3). Toplam piksel 1536² altı → $0.0675, üstü → $0.135
    SEEDREAM_IMAGE_SIZES = {
        'hd': {'width': 1664, 'height': 2496},
        'standard': {'width': 1248, 'height': 1872},
    }

    # Thread-safety: os.environ mutasyonu tek noktadan kontrol edilir
    _fal_key_lock = threading.Lock()

    def __init__(self, api_key):
        import os
        with FalProvider._fal_key_lock:
            os.environ['FAL_KEY'] = api_key
        self.api_key = api_key

    def _check_client(self):
        if fal_client is None:
            raise ImportError(
                'fal-client paketi kurulu degil. '
                'Kurulum: pip install fal-client'
            )

    def run_queued(self, endpoint, arguments, on_enqueue=None, timeout=180, poll_interval=2.0):
        """fal kuyruğuna gönder ve sonucu bekle — süre dolarsa işi İPTAL ETMEDEN hata ver.

        fal_client.subscribe(client_timeout=...) süre dolunca isteği iptal eder; bu,
        ücreti ödenmiş/kuyruktaki işin sonucunu kaybettirir. Burada iş kuyrukta kalır,
        request_id on_enqueue ile kaydedilmiştir ve cron sonucu sonradan alır.
        """
        self._check_client()
        handle = fal_client.submit(endpoint, arguments=arguments)
        if on_enqueue:
            on_enqueue(handle.request_id, endpoint)
        deadline = time.time() + timeout
        while True:
            status = handle.status()
            if isinstance(status, fal_client.Completed):
                return handle.get()
            if time.time() >= deadline:
                raise FalQueueTimeout(handle.request_id, timeout)
            time.sleep(poll_interval)

    def get_estimated_cost(self, endpoint):
        # Endpoint icin tahmini maliyeti dondur (USD).
        return self.ESTIMATED_COSTS.get(endpoint, 0.01)

    def _compute_cost(self, endpoint, n_outputs, n_refs, arguments):
        """Gerçek fal fiyatına göre maliyet (USD)."""
        n_outputs = max(1, n_outputs)
        if 'seedream/v4' in endpoint:
            return round(self.get_estimated_cost(endpoint) * n_outputs, 4)
        if 'seedream' in endpoint:
            size = arguments.get('image_size') or {}
            pixels = (size.get('width', 2048) * size.get('height', 2048)) if isinstance(size, dict) else 2048 * 2048
            per_image = 0.0675 if pixels <= 1536 * 1536 else 0.135
            return round(per_image * n_outputs + 0.0045 * max(0, n_refs - 1), 4)
        if 'nano-banana' in endpoint:
            return self.get_estimated_cost(endpoint) * n_outputs
        return self.get_estimated_cost(endpoint)

    def virtual_tryon(self, model_image_url, garment_image_url,
                      category='tops', mode='balanced', **kwargs):
        """Manken uzerine giydirme — thin API client.

        Prompt mantigi garment_analyzer.py'de merkezi olarak olusturulur.
        Bu fonksiyon sadece:
        1. Image URL'leri hazirlar (Figure indexleme)
        2. Detail referans Figure notlarini ekler
        3. fal_client.subscribe() ile API cagrisini yapar
        """
        self._check_client()

        model_name = kwargs.get('model_name') or 'tryon-v1.6'
        endpoint = kwargs.get('endpoint')
        if not endpoint:
            if 'seedream/v4' in model_name:
                endpoint = self.ENDPOINTS['seedream_v4']
            elif 'seedream' in model_name:
                endpoint = self.ENDPOINTS['seedream']
            elif 'nano-banana' in model_name:
                endpoint = self.ENDPOINTS['nano_banana']
            elif 'max' in model_name:
                endpoint = 'fal-ai/fashn/tryon-max'
            elif 'v1.6' in model_name or 'v1-6' in model_name:
                endpoint = self.ENDPOINTS['tryon_fashn']
            else:
                endpoint = self.ENDPOINTS['tryon_fashn']

        prompt = kwargs.get('prompt', '')
        negative_prompt = kwargs.get('negative_prompt', '')
        photo_type = kwargs.get('photo_type', 'front')

        n_refs = 0
        if 'seedream' in endpoint:
            # ═══ SEEDREAM (v5 Pro Edit / v4 Edit) ═══
            # v5 Pro şeması: prompt, image_urls(<=10), image_size, num_images, output_format,
            # sync_mode, enable_safety_checker. seed / negative_prompt / aspect_ratio /
            # resolution DESTEKLENMEZ (gönderilirse sessizce yok sayılır), seed döndürmez.
            # v4 Edit şeması: prompt, image_urls, image_size, num_images, max_images, seed,
            # enable_safety_checker, enhance_prompt_mode; output_format YOK; seed döndürür.
            # Görsel rolleri prompt şablonlarıyla eşleşir:
            #   Image 1 = manken, Image 2 = ürün, Image 3 = ön görünüm (back/side)
            image_urls_list = [model_image_url, garment_image_url]
            front_output_url = kwargs.get('front_output_url')
            if front_output_url and photo_type in ('back', 'side'):
                image_urls_list.append(front_output_url)

            enhanced_prompt = prompt
            detail_urls = kwargs.get('detail_urls') or []
            for du in detail_urls:
                image_urls_list.append(du)
                enhanced_prompt += (
                    f" Image {len(image_urls_list)} is a close-up texture reference of the same garment."
                )
            image_urls_list = image_urls_list[:10]
            n_refs = len(image_urls_list)

            arguments = {
                'prompt': enhanced_prompt,
                'image_urls': image_urls_list,
                'image_size': kwargs.get('image_size') or self.SEEDREAM_IMAGE_SIZES['hd'],
                'num_images': max(1, min(6, int(kwargs.get('num_samples') or 1))),
                'enable_safety_checker': bool(kwargs.get('enable_safety_checker', True)),
            }
            if 'seedream/v4' in endpoint:
                arguments['max_images'] = 1
                arguments['enhance_prompt_mode'] = 'standard'
                if kwargs.get('seed'):
                    arguments['seed'] = int(kwargs['seed'])
            else:
                arguments['output_format'] = 'png' if kwargs.get('output_format') == 'png' else 'jpeg'

        elif 'nano-banana' in endpoint:
            # ═══ NANO-BANANA PATH ═══ (aspect_ratio / resolution / negative destekler)
            # Sıra Seedream ile aynı: şablonlar Image 1 = manken, Image 2 = ürün varsayar
            image_urls_list = [model_image_url, garment_image_url]
            front_output_url = kwargs.get('front_output_url')
            if front_output_url and photo_type in ('back', 'side'):
                image_urls_list.append(front_output_url)
            arguments = {
                'prompt': prompt,
                'image_urls': image_urls_list,
                'aspect_ratio': '2:3',
                'output_format': 'jpeg',
                'resolution': str(kwargs.get('resolution', '2k')).lower(),
                'num_images': kwargs.get('num_samples', 1),
                'safety_tolerance': '4',
                'limit_generations': True,
                'enable_watermark': False,
            }
            if negative_prompt:
                arguments['negative_prompt'] = negative_prompt
            if kwargs.get('seed'):
                arguments['seed'] = int(kwargs['seed'])

        else:
            # ═══ FASHN PATH ═══
            fal_category = {
                'tops': 'tops',
                'bottoms': 'bottoms',
                'one_piece': 'one-piece',
                'one-piece': 'one-piece',
                'full-body': 'one-piece',
                'dress': 'one-piece',
            }.get(category, 'auto')  # ayakkabı/çanta/aksesuar: modele bırak

            arguments = {
                'model_image': model_image_url,
                'garment_image': garment_image_url,
                'category': fal_category,
                'mode': mode,
                'garment_photo_type': kwargs.get('garment_photo_type', 'flat-lay'),
                'enable_watermark': False,
            }
            # FASHN v1.6 şeması prompt / negative_prompt içermez

            if kwargs.get('seed'):
                arguments['seed'] = int(kwargs['seed'])

        # ═══ RATE LIMIT RETRY ═══
        import time
        max_retries = 2
        backoff_factor = 4
        result = None
        # fal kuyruğa aldığı anda request_id'yi çağırana bildir: worker ölse ya da
        # bekleme süresi dolsa bile sonuç cron tarafından fal'den alınır (yeniden ücret yok)
        on_enqueue = kwargs.get('on_enqueue')
        for attempt in range(max_retries):
            try:
                result = self.run_queued(endpoint, arguments, on_enqueue=on_enqueue, timeout=180)
                break
            except Exception as e:
                error_str = str(e).lower()
                # Dar eşleşme: "limit" içeren her hata (ör. içerik/boyut limiti)
                # ücretli işi yeniden göndermemeli
                is_rate_limit = (
                    '429' in error_str or
                    'rate limit' in error_str or
                    'too many requests' in error_str
                )
                if is_rate_limit and attempt < max_retries - 1:
                    sleep_time = backoff_factor * (2 ** attempt)
                    _logger.warning(
                        "fal.ai Rate Limit asildi. %d saniye beklenip tekrar denenecek (Deneme %d/%d). Hata: %s",
                        sleep_time, attempt + 1, max_retries, e
                    )
                    time.sleep(sleep_time)
                else:
                    raise

        # ═══ SONUÇ PARSE ═══
        image_urls = []
        if isinstance(result, dict):
            if 'images' in result and isinstance(result['images'], list):
                for img in result['images']:
                    if isinstance(img, dict):
                        u = img.get('url', '')
                        if u:
                            image_urls.append(u)
                    elif isinstance(img, str) and img:
                        image_urls.append(img)
            elif 'image' in result and result['image']:
                if isinstance(result['image'], dict):
                    u = result['image'].get('url', '')
                    if u:
                        image_urls.append(u)
                elif isinstance(result['image'], str) and result['image']:
                    image_urls.append(result['image'])

        image_url = image_urls[0] if image_urls else ''
        request_id = result.get('request_id', '') if isinstance(result, dict) else ''

        seed_val = None
        if isinstance(result, dict):
            seed_val = result.get('seed')
        else:
            seed_val = getattr(result, 'seed', None)

        return {
            'image_urls': image_urls,
            'image_url': image_url,
            'cost': self._compute_cost(endpoint, len(image_urls), n_refs, arguments),
            'request_id': request_id,
            'seed': seed_val,
        }
    # Birincil: Bria Eraser — prompt almaz, bölgeyi çevresiyle doldurur. Metin
    # istemi olmadığı için silinen yere "etiket/logo" gibi yeni bir nesne çizemez.
    # Maske: beyaz (255) = silinecek alan (Bria dokümantasyonu).
    ERASE_APP = 'fal-ai/bria/eraser'
    # Yedek: FLUX.1 Pro Fill. İstem SADECE olumlu olmalı: "tag/label" gibi nesne
    # adları olumsuzlansa bile model onları çizme eğilimindedir.
    FILL_APP = 'fal-ai/flux-pro/v1/fill'
    FILL_PROMPT = (
        "Plain fabric continuing seamlessly, identical to the surrounding garment "
        "in color, texture, weave and pattern."
    )

    def erase_regions(self, image_base64, tag_boxes, prompt=None, timeout=120, pad_ratio=0.25):
        """Kutuları maskeleyip bölgeyi çevresindeki kumaşla doldur (Bria, olmazsa FLUX Fill).

        upload_image görseli küçültüp WebP'ye çevirdiği için kullanılmaz: silme
        modelleri görsel ve maskenin aynı boyutta olmasını ister; ikisi de burada yüklenir.

        Returns:
            (bytes veya None, float cost)
        """
        self._check_client()
        import io
        import requests as req_lib
        from PIL import Image, ImageDraw
        from .garment_preprocessor import protect_box_pixels, tag_box_to_pixels

        raw = image_base64.decode('ascii') if isinstance(image_base64, bytes) else image_base64
        original = Image.open(io.BytesIO(base64.b64decode(raw))).convert('RGB')
        img = original.copy()
        if max(img.size) > 2048:
            img.thumbnail((2048, 2048), Image.LANCZOS)
        w, h = img.size
        mask = Image.new('L', (w, h), 0)
        draw = ImageDraw.Draw(mask)
        drawn = 0
        for item in tag_boxes or []:
            rect = tag_box_to_pixels(item, w, h, pad_ratio=pad_ratio)
            if rect:
                draw.rectangle(rect, fill=255)  # beyaz = doldurulacak alan
                drawn += 1
        if not drawn:
            return None, 0.0
        # Etiketin değdiği ürün detayları (fermuar ucu, düğme, logo) maskeden çıkarılır
        for item in tag_boxes or []:
            for rect in protect_box_pixels(item, w, h):
                draw.rectangle(rect, fill=0)

        img_buf, mask_buf = io.BytesIO(), io.BytesIO()
        img.save(img_buf, format='JPEG', quality=95)
        mask.save(mask_buf, format='PNG')
        image_url = fal_client.upload(img_buf.getvalue(), 'image/jpeg', file_name='garment.jpg')
        mask_url = fal_client.upload(mask_buf.getvalue(), 'image/png', file_name='mask.png')

        def _first_url(result):
            result = result or {}
            image = result.get('image')
            if isinstance(image, dict) and image.get('url'):
                return image['url']
            images = result.get('images') or []
            return images[0].get('url') if images and isinstance(images[0], dict) else ''

        out_url, cost, used = '', 0.0, self.ERASE_APP
        try:
            out_url = _first_url(fal_client.subscribe(self.ERASE_APP, arguments={
                'image_url': image_url,
                'mask_url': mask_url,
                'mask_type': 'manual',
            }, client_timeout=timeout))
            cost = 0.04
        except Exception as e:
            _logger.warning('Bria Eraser başarısız, FLUX Fill deneniyor: %s', e)
        if not out_url:
            used = self.FILL_APP
            out_url = _first_url(fal_client.subscribe(self.FILL_APP, arguments={
                'prompt': prompt or self.FILL_PROMPT,
                'image_url': image_url,
                'mask_url': mask_url,
                'output_format': 'png',
                'safety_tolerance': '5',
            }, client_timeout=timeout))
            cost = round(0.05 * max(1.0, w * h / 1e6), 4)
        if not out_url:
            return None, 0.0
        _logger.info('%s ile %d bölge silindi (%dx%d, $%.3f)', used, drawn, w, h, cost)
        erased = Image.open(io.BytesIO(req_lib.get(out_url, timeout=60).content)).convert('RGB')
        # Yalnız maskelenen bölgeler orijinale yapıştırılır: görselin geri kalanı ve
        # çözünürlüğü (ör. 1664x2496) aynen korunur, yeniden sıkıştırma kaybı olmaz
        if erased.size != original.size:
            erased = erased.resize(original.size, Image.LANCZOS)
        full_mask = mask.resize(original.size, Image.NEAREST) if mask.size != original.size else mask
        original.paste(erased, (0, 0), full_mask)
        out = io.BytesIO()
        original.save(out, format='JPEG', quality=95)
        return out.getvalue(), cost

    def single_image_edit(self, image_base64, prompt, timeout=120):
        """Tek görseli Seedream ile düzenle (etiket silme, manken bacak düzeltme vb.).

        Returns:
            (bytes veya None, float cost): düzenlenmiş görselin ham baytları ve maliyet
        """
        self._check_client()
        import requests as req_lib
        app = self.ENDPOINTS['seedream']
        image = image_base64.decode('ascii') if isinstance(image_base64, bytes) else image_base64
        url = self.upload_image(image)
        result = fal_client.subscribe(app, arguments={'prompt': prompt, 'image_urls': [url]},
                                      client_timeout=timeout)
        images = (result or {}).get('images') or []
        out_url = images[0].get('url') if images and isinstance(images[0], dict) else ''
        if not out_url:
            return None, 0.0
        return req_lib.get(out_url, timeout=60).content, self.get_estimated_cost(app)

    def generate_mannequin(self, prompt, **kwargs):
        # AI ile manken fotografi olustur - FLUX schnell.
        self._check_client()

        width = kwargs.get('width', 864)
        height = kwargs.get('height', 1296)

        result = fal_client.subscribe(
            self.ENDPOINTS['flux_schnell'],
            arguments={
                'prompt': prompt,
                'image_size': {'width': width, 'height': height},
                'num_images': 1,
                'enable_watermark': False,
            },
            client_timeout=120,
        )

        image_url = ''
        if isinstance(result, dict):
            imgs = result.get('images', [])
            if imgs and isinstance(imgs, list):
                first = imgs[0]
                if isinstance(first, dict):
                    image_url = first.get('url', '')
                elif isinstance(first, str):
                    image_url = first
        if image_url:
            import requests
            img_data = requests.get(image_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return None

    def remove_background(self, image_base64):
        # Arka plan kaldirma - birefnet.
        self._check_client()

        image_url = self.upload_image(image_base64)
        result = fal_client.subscribe(
            self.ENDPOINTS['bg_remove'],
            arguments={'image_url': image_url},
            client_timeout=60,
        )
        output_url = ''
        if isinstance(result, dict):
            img_val = result.get('image')
            if isinstance(img_val, dict):
                output_url = img_val.get('url', '')
            elif isinstance(img_val, str):
                output_url = img_val
        if output_url:
            import requests
            img_data = requests.get(output_url, timeout=60).content
            return base64.b64encode(img_data).decode()
        return image_base64

    def upload_image(self, image_base64, content_type='image/jpeg'):
        # Gorseli fal CDN'e yukle - otomatik retry ve fallback ile.
        self._check_client()
        if isinstance(image_base64, bytes):
            image_base64 = image_base64.decode('ascii')
        if image_base64.startswith('data:'):
            image_base64 = image_base64.split(';base64,', 1)[1]
        raw_bytes = base64.b64decode(image_base64)
        
        # ═══ WEBP OPTİMİZASYONU ═══
        # Kalite kaybı olmadan dosya boyutunu %80-90 oranında küçülterek
        # Fal CDN yükleme ve GPU indirme/işleme süresini dramatik şekilde hızlandırır.
        try:
            from PIL import Image as _PILImage
            try:
                # Odoo Pillow'u temel formatlarla sınırlar; WebP eklentisini açıkça yükle
                from PIL import WebPImagePlugin  # noqa: F401
            except ImportError:
                pass
            import io as _io
            _img = _PILImage.open(_io.BytesIO(raw_bytes))
            _fmt = (_img.format or '').upper()
            w, h = _img.size
            if _fmt != 'WEBP' or max(w, h) > 1600 or len(raw_bytes) > 1024 * 1024:
                if _img.mode in ('RGBA', 'LA', 'P'):
                    if _img.mode == 'P':
                        _img = _img.convert('RGBA')
                elif _img.mode != 'RGB':
                    _img = _img.convert('RGB')
                if max(w, h) > 1600:
                    _img.thumbnail((1600, 1600), _PILImage.LANCZOS)
                _out = _io.BytesIO()
                # Önce WebP dene, yoksa JPEG'e düş
                try:
                    _img.save(_out, format='WEBP', quality=92, method=4)
                    raw_bytes = _out.getvalue()
                    content_type = 'image/webp'
                    _logger.info('fal CDN yükleme öncesi WebP formatına optimize edildi: %d KB (%dx%d)', len(raw_bytes) // 1024, _img.width, _img.height)
                except (KeyError, OSError):
                    _logger.warning('Pillow WebP destegi yok, JPEG fallback ile optimize ediliyor')
                    _out = _io.BytesIO()
                    _rgb = _img.convert('RGB') if _img.mode != 'RGB' else _img
                    _rgb.save(_out, format='JPEG', quality=92, optimize=True)
                    raw_bytes = _out.getvalue()
                    content_type = 'image/jpeg'
                    _logger.info('fal CDN yükleme öncesi JPEG formatına optimize edildi: %d KB (%dx%d)', len(raw_bytes) // 1024, _img.width, _img.height)
            elif _fmt == 'WEBP':
                content_type = 'image/webp'
        except Exception as _re:
            _logger.warning('Görsel optimizasyonu başarısız, orijinal gönderilecek: %s', _re)
        
        # 1. fal_client.upload (HTTP REST - primary)
        file_name = 'image.webp' if content_type == 'image/webp' else 'image.jpg'
        for attempt in range(3):
            try:
                return fal_client.upload(raw_bytes, content_type, file_name=file_name)
            except Exception as e:
                _logger.warning('fal CDN yükleme denemesi %d/3 başarısız: %s', attempt + 1, e)
                if attempt < 2:
                    time.sleep(2 ** attempt)
        
        # 2. REST API doğrudan deneme (fallback)
        try:
            import requests as _req
            resp = _req.post(
                'https://rest.alpha.fal.ai/storage/upload/initiate',
                headers={'Authorization': f'Key {self.api_key}'},
                json={'content_type': content_type, 'file_name': file_name},
                timeout=15,
            )
            if resp.status_code in (200, 201):
                init_data = resp.json()
                upload_url = init_data.get('upload_url')
                file_url = init_data.get('file_url')
                if upload_url and file_url:
                    put_resp = _req.put(upload_url, data=raw_bytes, headers={'Content-Type': content_type}, timeout=30)
                    if put_resp.status_code in (200, 201):
                        return file_url
        except Exception as e2:
            _logger.warning('fal REST doğrudan yükleme de başarısız: %s', e2)
        
        # 3. Son çare: base64 data URI dönder
        _logger.warning('fal CDN yükleme tamamen başarısız, data URI fallback')
        return f'data:{content_type};base64,{image_base64}'
