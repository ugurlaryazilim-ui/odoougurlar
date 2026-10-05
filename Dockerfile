FROM odoo:19

USER root
# 0. Pillow WebP desteği — PyPI wheel zaten WebP içeriyor,
#    sistem python3-pil'i override etmek yeterli (build araçları gereksiz)
RUN pip install --break-system-packages --force-reinstall --no-cache-dir Pillow \
    && python3 -c "\
import PIL; print('PIL konum:', PIL.__file__); \
from PIL import features; \
w = features.check('webp'); print('WebP:', w); \
j = features.check('jpg'); print('JPEG:', j)"

# 1. Gerekli Python Kütüphanelerinin (Amazon SP-API eklentisi dahil) Yüklenmesi
RUN pip install --break-system-packages pandas "openpyxl>=3.1.5" boto3 requests-auth-aws-sigv4 pymssql deep-translator
RUN pip install --break-system-packages --ignore-installed fal-client
RUN pip install --break-system-packages --ignore-installed fashn

# 1.5. Barkod etiketindeki Courier yazısı: reportlab eski gsfonts adını (n022003l.pfb) arıyor,
#      Debian trixie'de yok ("Can't find .pfb for face 'Courier'") — Nimbus Mono'ya bağla
RUN F=/usr/lib/python3/dist-packages/reportlab/fonts G=/usr/share/fonts/type1/gsfonts \
 && mkdir -p $G \
 && ln -sf $F/NimbusMonoPS-Regular.pfb $G/n022003l.pfb \
 && ln -sf $F/NimbusMonoPS-Bold.pfb $G/n022004l.pfb \
 && ln -sf $F/NimbusMonoPS-Italic.pfb $G/n022023l.pfb \
 && ln -sf $F/NimbusMonoPS-BoldItalic.pfb $G/n022024l.pfb

# 2. Yazdığımız tüm eklentileri (addons klasörü) ve yapılandırma dosyasını Docker İmajının içine kopyalıyoruz
# --chown: ayrı "chown -R" katmanı tüm eklentileri imaja ikinci kez yazıyordu (yavaş build, büyük imaj)
# /opt/ugurlar-addons: odoo imajı /mnt/extra-addons'u VOLUME tanımlıyor; eklentiler oraya kopyalanınca
# her deploy'da tüm eklentilerin kopyası yeni bir isimsiz volume'a yazılıp sunucuda birikiyordu.
# addons_path önce /mnt/extra-addons'a bakar: yerelde canlı bağlanan kod, prod'da (boş) imaj kopyası kullanılır.
COPY --chown=odoo:odoo ./addons /opt/ugurlar-addons
COPY --chown=odoo:odoo ./config /etc/odoo

# 2.5. Orijinal Odoo kodundaki MemoryError hatasını yamalıyoruz
RUN python3 /opt/ugurlar-addons/patch_odoo.py

USER odoo
