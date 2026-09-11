PAYSTARS BOT - RENDER + POSTGRESQL

FAYLLAR:
main.py
requirements.txt
render.yaml

RENDER:
1. PostgreSQL Database yarating.
2. Web Service yarating.
3. GitHub repo ulang yoki fayllarni repo'ga yuklang.
4. Environment Variables:
BOT_TOKEN
ADMIN_ID
PAYSTARS_API_KEY
CARD_NUMBER
CARD_OWNER
MARKUP_PERCENT=4.5
PAYSTARS_API=https://paystars.uz/api/v1
5. PostgreSQL Internal Database URL'ni Web Service'ga DATABASE_URL sifatida ulang.
6. Build: pip install -r requirements.txt
7. Start: python main.py

BALANS:
Balans to‘ldirish -> karta -> To‘lov qildim -> chek -> admin Qabul qilish -> summa -> balans.

MUHIM:
SQLite ishlatilmaydi. Ma’lumotlar PostgreSQL'da saqlanadi va Render restart/redeploy bo‘lganda saqlanib qoladi.
