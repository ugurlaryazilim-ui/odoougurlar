import requests
import json

url_create = "https://evo.ugurlar.com/instance/create"
headers = {
    "apikey": "B4T9H7G2K5L8M1N4P6Q3R9S7T2V5W8X",
    "Content-Type": "application/json"
}

res = requests.post(url_create, headers=headers, json={"instanceName": "odoo", "qrcode": True})
print(f"Status: {res.status_code}")
print(f"Body: {res.text}")
