FROM odoo:19

USER root
# 0. Pillow'u WebP desteği ile kaynaktan derle
#    Önce sistem python3-pil'i kaldır (pip Pillow'u gölgeliyordu!)
#    Sonra kaynak derleme yap, doğrula, build araçlarını temizle
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3-dev libwebp-dev libjpeg-dev zlib1g-dev \
    && dpkg --force-depends -r python3-pil python3-pil.imagetk 2>/dev/null || true \
    && pip install --break-system-packages --no-binary Pillow --force-reinstall --no-cache-dir Pillow \
    && python3 -c "from PIL import features; ok=features.check('webp'); print('WebP support:', ok); assert ok, 'PILLOW WEBP DESTEĞI KURULAMADI!'" \
    && apt-get purge -y build-essential python3-dev \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# 1. Gerekli Python Kütüphanelerinin (Amazon SP-API eklentisi dahil) Yüklenmesi
RUN pip install --break-system-packages pandas "openpyxl>=3.1.5" boto3 requests-auth-aws-sigv4 pymssql deep-translator
RUN pip install --break-system-packages --ignore-installed fal-client
RUN pip install --break-system-packages --ignore-installed fashn

# 2. Yazdığımız tüm eklentileri (addons klasörü) ve yapılandırma dosyasını Docker İmajının içine kopyalıyoruz
COPY ./addons /mnt/extra-addons
COPY ./config /etc/odoo

# 2.5. Orijinal Odoo kodundaki MemoryError hatasını yamalıyoruz
RUN python3 /mnt/extra-addons/patch_odoo.py

# 3. İzinlerin Odoo kullanıcısına devredilmesi (Production güvenliği)
RUN chown -R odoo:odoo /mnt/extra-addons \
 && chown -R odoo:odoo /etc/odoo

USER odoo
