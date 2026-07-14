import requests
import json
import webbrowser
import os

url_create = "https://evo.ugurlar.com/instance/create"
url_connect = "https://evo.ugurlar.com/instance/connect/odoo"
headers = {
    "apikey": "B4T9H7G2K5L8M1N4P6Q3R9S7T2V5W8X",
    "Content-Type": "application/json"
}

# 1. Try to create the instance
res = requests.post(url_create, headers=headers, json={"instanceName": "odoo", "qrcode": True})
b64_qr = None

if res.ok:
    data = res.json()
    if 'qrcode' in data and 'base64' in data['qrcode']:
        b64_qr = data['qrcode']['base64']
else:
    # 2. If it already exists, fetch the QR code
    res = requests.get(url_connect, headers=headers)
    if res.ok:
        data = res.json()
        if 'base64' in data:
            b64_qr = data['base64']

if b64_qr:
    html_path = os.path.abspath("qr_scan.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(f'''
        <html>
        <body style="display:flex; justify-content:center; align-items:center; height:100vh; background-color:#f0f2f5;">
            <div style="background:white; padding:40px; border-radius:20px; box-shadow:0 10px 30px rgba(0,0,0,0.1); text-align:center;">
                <h2 style="font-family:sans-serif; color:#333;">WhatsApp'ı Bağlayın</h2>
                <p style="font-family:sans-serif; color:#666;">WhatsApp > Bağlı Cihazlar menüsünden bu QR kodu okutun.</p>
                <img src="{b64_qr}" style="width:300px; height:300px; margin-top:20px;" />
            </div>
        </body>
        </html>
        ''')
    print("QR Code HTML created successfully.")
    webbrowser.open(f"file://{html_path}")
else:
    print(f"Failed to get QR code. Status: {res.status_code}, Response: {res.text}")
