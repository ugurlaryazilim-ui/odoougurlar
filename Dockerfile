FROM odoo:19

USER root
# 1. Gerekli Python Kütüphanelerinin (Amazon SP-API eklentisi dahil) Yüklenmesi
RUN pip install --break-system-packages pandas "openpyxl>=3.1.5" boto3 requests-auth-aws-sigv4

# 2. Yazdığımız tüm eklentileri (addons klasörü) Docker İmajının içine kopyalıyoruz
COPY ./addons /mnt/extra-addons

# 3. İzinlerin Odoo kullanıcısına devredilmesi (Production güvenliği)
RUN chown -R odoo:odoo /mnt/extra-addons

USER odoo
