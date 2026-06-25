FROM odoo:19

USER root
# 1. Gerekli Python Kütüphanelerinin (Amazon SP-API eklentisi dahil) Yüklenmesi
RUN pip install --break-system-packages pandas "openpyxl>=3.1.5" boto3 requests-auth-aws-sigv4 pymssql fal-client
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
