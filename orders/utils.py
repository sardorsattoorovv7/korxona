# orders/utils.py

import requests
from django.conf import settings

# Eslatma: Agar Siz django.contrib.sites dan foydalanmasangiz,
# from django.contrib.sites.models import Site qatorini o'chiring.

def send_telegram_notification(message):
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML'
    }
    
    try:
        # Telegram API ga so'rov yuborish
        response = requests.post(url, data=payload, timeout=5)
        
        # Muvaffaqiyatni tekshirish
        if response.status_code == 200:
            print(f"✅ TELEGRAM XABARI MUVAFFFAQIYATLI YUBORILDI (Chat ID: {chat_id})")
        else:
            # Telegram API xatosi
            print(f"❌ TELEGRAM XABARINI YUBORISHDA XATO! Status: {response.status_code}")
            print(f"❌ API JAVOBI: {response.json()}")
            
    except requests.exceptions.RequestException as e:
        # Tarmoq xatolari
        print(f"❌ TARMOQ XATOSI: Telegram serveriga ulanib bo'lmadi yoki timeout: {e}") 

# Eslatma: Ushbu faylda 'django.contrib.sites.models import Site' qatorini o'chirganingizga ishonch hosil qiling!