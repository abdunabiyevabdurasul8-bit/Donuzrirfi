import os
import asyncio
import logging
import uuid
from datetime import datetime

import requests
import psycopg2
from psycopg2.pool import SimpleConnectionPool

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)


# =========================================================
# SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
PAYSTARS_API_KEY = os.getenv("PAYSTARS_API_KEY", "").strip()
PAYSTARS_API = os.getenv(
    "PAYSTARS_API",
    "https://paystars.uz/api/v1"
).rstrip("/")

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

MARKUP_PERCENT = float(
    os.getenv("MARKUP_PERCENT", "4.5")
)

CARD_NUMBER = os.getenv(
    "CARD_NUMBER",
    "9860 6067 6078 9275"
)

CARD_OWNER = os.getenv(
    "CARD_OWNER",
    "A.Abdurasul "
)

PORT = int(os.getenv("PORT", "10000"))

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL",
    ""
).rstrip("/")


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

log = logging.getLogger(__name__)

pool = None


# =========================================================
# TIME
# =========================================================

def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# DATABASE
# =========================================================

def init_db():
    global pool

    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL topilmadi")

    pool = SimpleConnectionPool(
        1,
        8,
        DATABASE_URL,
        sslmode="require"
    )

    c = pool.getconn()

    try:
        x = c.cursor()

        x.execute("""
            CREATE TABLE IF NOT EXISTS users(
                user_id BIGINT PRIMARY KEY,
                username TEXT DEFAULT '',
                first_name TEXT DEFAULT '',
                balance NUMERIC(18,2) DEFAULT 0,
                joined_at TEXT,
                last_seen TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)

        x.execute("""
            CREATE TABLE IF NOT EXISTS orders(
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT,
                provider_order_id TEXT,
                order_type TEXT,
                username TEXT,
                quantity INTEGER DEFAULT 0,
                months INTEGER DEFAULT 0,
                provider_cost NUMERIC(18,2) DEFAULT 0,
                sell_price NUMERIC(18,2) DEFAULT 0,
                status TEXT DEFAULT 'Kutilmoqda',
                created_at TEXT,
                updated_at TEXT
            )
        """)

        x.execute("""
            CREATE TABLE IF NOT EXISTS payments(
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT,
                amount NUMERIC(18,2) DEFAULT 0,
                status TEXT DEFAULT 'Kutilmoqda',
                created_at TEXT,
                approved_at TEXT,
                admin_id BIGINT
            )
        """)

        x.execute("""
            CREATE TABLE IF NOT EXISTS promocodes(
                code TEXT PRIMARY KEY,
                amount NUMERIC(18,2) DEFAULT 0,
                limit_count INTEGER DEFAULT 1,
                used_count INTEGER DEFAULT 0,
                created_at TEXT
            )
        """)

        x.execute("""
            CREATE TABLE IF NOT EXISTS promo_uses(
                user_id BIGINT,
                code TEXT,
                used_at TEXT,
                PRIMARY KEY(user_id, code)
            )
        """)

        c.commit()

    finally:
        pool.putconn(c)


def fetchone(q, p=()):
    c = pool.getconn()

    try:
        x = c.cursor()
        x.execute(q, p)
        r = x.fetchone()

        if not r:
            return None

        return dict(
            zip(
                [d[0] for d in x.description],
                r
            )
        )

    finally:
        pool.putconn(c)


def fetchall(q, p=()):
    c = pool.getconn()

    try:
        x = c.cursor()
        x.execute(q, p)

        rows = x.fetchall()

        cols = [
            d[0]
            for d in x.description
        ]

        return [
            dict(zip(cols, r))
            for r in rows
        ]

    finally:
        pool.putconn(c)


def execute(q, p=()):
    c = pool.getconn()

    try:
        x = c.cursor()
        x.execute(q, p)

        n = x.rowcount

        c.commit()

        return n

    except:
        c.rollback()
        raise

    finally:
        pool.putconn(c)


# =========================================================
# USERS
# =========================================================

def register(u):
    c = pool.getconn()

    try:
        x = c.cursor()

        x.execute(
            "SELECT 1 FROM users WHERE user_id=%s",
            (u.id,)
        )

        if x.fetchone():

            x.execute("""
                UPDATE users
                SET username=%s,
                    first_name=%s,
                    last_seen=%s,
                    is_active=1
                WHERE user_id=%s
            """, (
                u.username or "",
                u.first_name or "",
                now(),
                u.id
            ))

        else:

            x.execute("""
                INSERT INTO users(
                    user_id,
                    username,
                    first_name,
                    balance,
                    joined_at,
                    last_seen,
                    is_active
                )
                VALUES(
                    %s,%s,%s,0,%s,%s,1
                )
            """, (
                u.id,
                u.username or "",
                u.first_name or "",
                now(),
                now()
            ))

        c.commit()

    finally:
        pool.putconn(c)


def balance_of(uid):
    r = fetchone(
        "SELECT balance FROM users WHERE user_id=%s",
        (uid,)
    )

    return float(r["balance"]) if r else 0


def change_balance(uid, amount):
    execute(
        "UPDATE users SET balance=balance+%s WHERE user_id=%s",
        (amount, uid)
    )


# =========================================================
# PAYSTARS API
# =========================================================

def headers(key=None):

    h = {
        "X-API-Key": PAYSTARS_API_KEY,
        "Content-Type": "application/json"
    }

    if key:
        h["Idempotency-Key"] = key

    return h


def api_get(path):

    r = requests.get(
        PAYSTARS_API + path,
        headers=headers(),
        timeout=25
    )

    try:
        d = r.json()
    except:
        d = {
            "detail": r.text
        }

    if not r.ok:
        raise Exception(
            f"API {r.status_code}: {d}"
        )

    return d


def api_post(path, payload, key=None):

    r = requests.post(
        PAYSTARS_API + path,
        headers=headers(key),
        json=payload,
        timeout=30
    )

    try:
        d = r.json()
    except:
        d = {
            "detail": r.text
        }

    if not r.ok:
        raise Exception(
            f"API {r.status_code}: {d}"
        )

    return d


def account():
    return api_get("/account")


def prices():
    return api_get("/prices")


def check_user(username, kind):
    return api_post(
        "/check-username",
        {
            "username": username,
            "kind": kind
        }
    )


def buy_stars(username, quantity, token):

    return api_post(
        "/stars/buy",
        {
            "username": username,
            "quantity": quantity,
            "verification_token": token
        },
        "stars_" + str(uuid.uuid4())
    )


def buy_premium(username, months, token):

    return api_post(
        "/premium/buy",
        {
            "username": username,
            "months": months,
            "verification_token": token
        },
        "premium_" + str(uuid.uuid4())
    )


def sell(value):
    return round(
        float(value) * (
            1 + MARKUP_PERCENT / 100
        ),
        2
    )


# =========================================================
# ORDER STATUS
# =========================================================

def successful_status(status):

    s = str(status).lower().strip()

    return s in {
        "delivered",
        "completed",
        "complete",
        "success",
        "successful",
        "done"
    }


def status_text(status):

    if successful_status(status):
        return "✅ Muvaffaqiyatli"

    s = str(status).lower()

    if s in {
        "processing",
        "pending",
        "created"
    }:
        return "⏳ Jarayonda"

    if s in {
        "failed",
        "cancelled",
        "canceled",
        "error"
    }:
        return "❌ Bekor qilindi"

    return str(status)


# =========================================================
# KEYBOARDS
# =========================================================

def user_key():

    return ReplyKeyboardMarkup(
        [
            ["🛍️ Buyurtma berish"],
            ["💳 Balans to‘ldirish", "💰 Balans"],
            ["📦 Buyurtmalarim", "🎁 Promokod"],
            ["👤 Profil", "🏆 Reyting"],
            ["🆘 SOS / Admin"]
        ],
        resize_keyboard=True
    )


def admin_key():

    return ReplyKeyboardMarkup(
        [
            ["💰 Pul +", "💸 Pul −"],
            ["💳 To‘lovlar", "📊 Statistika"],
            ["👥 Foydalanuvchilar", "🏆 Reyting"],
            ["📦 Buyurtmalar", "🎁 Promokod"],
            ["📢 Post", "🔄 Katalog"],
            ["💰 PayStars balansi"],
            ["❌ Admin paneldan chiqish"]
        ],
        resize_keyboard=True
    )


USER_MENU = {
    "🛍️ Buyurtma berish",
    "💳 Balans to‘ldirish",
    "💰 Balans",
    "📦 Buyurtmalarim",
    "🎁 Promokod",
    "👤 Profil",
    "🏆 Reyting",
    "🆘 SOS / Admin"
}


ADMIN_MENU = {
    "💰 Pul +",
    "💸 Pul −",
    "💳 To‘lovlar",
    "📊 Statistika",
    "👥 Foydalanuvchilar",
    "📦 Buyurtmalar",
    "📢 Post",
    "🔄 Katalog",
    "💰 PayStars balansi",
    "❌ Admin paneldan chiqish"
}


# =========================================================
# START
# =========================================================

async def start(u, c):

    register(u.effective_user)

    c.user_data.clear()

    await u.message.reply_text(
        "👋 Assalomu alaykum!\n\n"
        "⭐ Telegram Stars va 💎 Telegram Premium "
        "xizmatlariga xush kelibsiz.",
        reply_markup=user_key()
    )


async def admin_cmd(u, c):

    if u.effective_user.id != ADMIN_ID:
        return

    c.user_data.clear()

    await u.message.reply_text(
        "👑 Admin panel",
        reply_markup=admin_key()
    )


# =========================================================
# BASIC USER FUNCTIONS
# =========================================================

async def balance(u, c):

    await u.message.reply_text(
        f"💰 <b>Balans</b>\n\n"
        f"<b>{balance_of(u.effective_user.id):,.0f} so‘m</b>",
        parse_mode="HTML"
    )


async def profile(u, c):

    r = fetchone(
        "SELECT * FROM users WHERE user_id=%s",
        (u.effective_user.id,)
    )

    n = fetchone(
        "SELECT COUNT(*) c FROM orders WHERE user_id=%s",
        (u.effective_user.id,)
    )["c"]

    un = (
        "@" + r["username"]
        if r["username"]
        else "Yo‘q"
    )

    await u.message.reply_text(
        f"👤 <b>Profil</b>\n\n"
        f"🆔 ID: <code>{r['user_id']}</code>\n"
        f"👤 Username: {un}\n"
        f"📝 Ism: {r['first_name']}\n"
        f"💰 Balans: {float(r['balance']):,.0f} so‘m\n"
        f"📦 Buyurtmalar: {n} ta\n"
        f"📅 Qo‘shilgan: {r['joined_at']}",
        parse_mode="HTML"
    )


# =========================================================
# SOS
# =========================================================

async def sos(u, c):

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💬 Admin bilan bog‘lanish",
                    url="https://t.me/donuz1"
                )
            ]
        ]
    )

    await u.message.reply_text(
        "🆘 <b>Yordam kerakmi?</b>\n\n"
        "Savol yoki muammo bo‘lsa, "
        "administrator bilan bog‘lanishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=kb
    )


# =========================================================
# CATALOG
# =========================================================

async def catalog(u, c):

    try:

        p = (
            await asyncio.to_thread(account)
        ).get("pricing", {})

        s = float(
            p.get("star_price", 0) or 0
        )

        text = (
            "🛍️ <b>Katalog</b>\n\n"
            f"⭐ 1 Stars: {sell(s):,.0f} so‘m\n"
            "⭐ Minimal: 50 Stars\n\n"
            f"💎 Premium 3 oy: "
            f"{sell(p.get('premium_3_price', 0)):,.0f} so‘m\n"
            f"💎 Premium 6 oy: "
            f"{sell(p.get('premium_6_price', 0)):,.0f} so‘m\n"
            f"💎 Premium 12 oy: "
            f"{sell(p.get('premium_12_price', 0)):,.0f} so‘m"
        )

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "⭐ Stars",
                        callback_data="buy_stars"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "💎 Premium",
                        callback_data="buy_premium"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Yopish",
                        callback_data="close"
                    )
                ]
            ]
        )

        await u.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=kb
        )

    except Exception:

        log.exception("catalog")

        await u.message.reply_text(
            "❌ Katalogni olishda xatolik."
        )


# =========================================================
# STARS
# =========================================================

SU, SQ = 1, 2


async def stars_start(u, c):

    q = u.callback_query

    await q.answer()

    c.user_data.clear()

    try:
        await q.message.delete()
    except:
        pass

    await q.message.chat.send_message(
        "⭐ <b>Telegram Stars</b>\n\n"
        "@username yuboring.\n\n"
        "Boshqa menyu tugmasini bossangiz "
        "jarayon bekor bo‘ladi.",
        parse_mode="HTML"
    )

    return SU


async def stars_username(u, c):

    t = u.message.text.strip()

    if (
        t in USER_MENU
        or t in ADMIN_MENU
        or not t
        or " " in t
        or len(t.lstrip("@")) > 64
    ):

        await u.message.reply_text(
            "❌ Username noto‘g‘ri.\n"
            "Masalan: @username"
        )

        return SU

    c.user_data["stars_username"] = t.lstrip("@")

    await u.message.reply_text(
        "🔢 Nechta Stars?\n\n"
        "Minimal: <b>50</b>",
        parse_mode="HTML"
    )

    return SQ


async def stars_quantity(u, c):

    try:
        q = int(u.message.text.strip())

    except:

        await u.message.reply_text(
            "❌ Faqat son yuboring."
        )

        return SQ

    if q < 50:

        await u.message.reply_text(
            "❌ Minimal 50 Stars."
        )

        return SQ

    name = c.user_data.get(
        "stars_username"
    )

    try:

        r = await asyncio.to_thread(
            check_user,
            name,
            "stars"
        )

        if not r.get("valid"):
            raise Exception(
                "Username Stars uchun yaroqsiz"
            )

        tok = r.get(
            "verification_token"
        )

        p = (
            await asyncio.to_thread(account)
        ).get("pricing", {})

        price = sell(
            float(
                p.get("star_price", 0)
            ) * q
        )

        c.user_data.update(
            stars_username=name,
            stars_quantity=q,
            stars_token=tok,
            stars_cost=price
        )

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Tasdiqlash",
                        callback_data="confirm_stars"
                    ),
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data="cancel_order"
                    )
                ]
            ]
        )

        await u.message.reply_text(
            f"⭐ <b>Stars</b>\n\n"
            f"👤 @{name}\n"
            f"⭐ {q}\n"
            f"💰 {price:,.0f} so‘m\n"
            f"💳 Balans: "
            f"{balance_of(u.effective_user.id):,.0f} so‘m\n\n"
            "Tasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=kb
        )

    except Exception:

        log.exception("stars check")

        c.user_data.clear()

        await u.message.reply_text(
            "❌ Foydalanuvchini tekshirishda xatolik.",
            reply_markup=user_key()
        )

    return ConversationHandler.END


async def stars_fallback(u, c):

    c.user_data.clear()

    await route(u, c)

    return ConversationHandler.END


# =========================================================
# PREMIUM
# =========================================================

async def premium_start(u, c):

    q = u.callback_query

    await q.answer()

    c.user_data.clear()

    try:
        await q.message.delete()
    except:
        pass

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "3 oy",
                    callback_data="premium_month_3"
                ),
                InlineKeyboardButton(
                    "6 oy",
                    callback_data="premium_month_6"
                )
            ],
            [
                InlineKeyboardButton(
                    "12 oy",
                    callback_data="premium_month_12"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="close"
                )
            ]
        ]
    )

    await q.message.chat.send_message(
        "💎 <b>Premium</b>\n\n"
        "Muddatni tanlang:",
        parse_mode="HTML",
        reply_markup=kb
    )


async def premium_month(u, c):

    q = u.callback_query

    await q.answer()

    m = int(
        q.data.split("_")[-1]
    )

    c.user_data.clear()

    c.user_data[
        "premium_months"
    ] = m

    try:
        await q.message.delete()
    except:
        pass

    await q.message.chat.send_message(
        "👤 Premium kimga?\n\n"
        "@username yuboring.\n\n"
        "Boshqa menyu tugmasi "
        "jarayonni bekor qiladi.",
        parse_mode="HTML"
    )

    c.user_data[
        "waiting_premium_username"
    ] = True


async def premium_username(u, c):

    t = u.message.text.strip()

    if t in USER_MENU or t in ADMIN_MENU:

        c.user_data.clear()

        await route(u, c)

        return

    name = t.lstrip("@")

    m = c.user_data.get(
        "premium_months"
    )

    if not name or " " in name:

        await u.message.reply_text(
            "❌ Username noto‘g‘ri."
        )

        return

    try:

        r = await asyncio.to_thread(
            check_user,
            name,
            "premium"
        )

        if not r.get("valid"):
            raise Exception(
                "Bu username Premium uchun mavjud emas"
            )

        tok = r.get(
            "verification_token"
        )

        p = (
            await asyncio.to_thread(account)
        ).get("pricing", {})

        price = sell(
            p.get(
                f"premium_{m}_price",
                0
            )
        )

        if not tok or price <= 0:
            raise Exception(
                "Premium maʼlumoti olinmadi"
            )

        c.user_data.update(
            premium_username=name,
            premium_months=m,
            premium_token=tok,
            premium_cost=price
        )

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Tasdiqlash",
                        callback_data="confirm_premium"
                    ),
                    InlineKeyboardButton(
                        "❌ Bekor qilish",
                        callback_data="cancel_order"
                    )
                ]
            ]
        )

        await u.message.reply_text(
            f"💎 <b>Premium</b>\n\n"
            f"👤 @{name}\n"
            f"💎 {m} oy\n"
            f"💰 {price:,.0f} so‘m\n"
            f"💳 Balans: "
            f"{balance_of(u.effective_user.id):,.0f} so‘m\n\n"
            "Tasdiqlaysizmi?",
            parse_mode="HTML",
            reply_markup=kb
        )

    except Exception:

        log.exception("premium")

        c.user_data.clear()

        await u.message.reply_text(
            "❌ Premium maʼlumotlarini olishda xatolik.",
            reply_markup=user_key()
        )


# =========================================================
# CONFIRM ORDER
# =========================================================

async def confirm(u, c):

    q = u.callback_query

    await q.answer()

    uid = q.from_user.id

    stars = (
        q.data == "confirm_stars"
    )

    if stars:

        name = c.user_data.get(
            "stars_username"
        )

        token = c.user_data.get(
            "stars_token"
        )

        qty = c.user_data.get(
            "stars_quantity",
            0
        )

        months = 0

        price = float(
            c.user_data.get(
                "stars_cost",
                0
            ) or 0
        )

    else:

        name = c.user_data.get(
            "premium_username"
        )

        token = c.user_data.get(
            "premium_token"
        )

        qty = 0

        months = c.user_data.get(
            "premium_months",
            0
        )

        price = float(
            c.user_data.get(
                "premium_cost",
                0
            ) or 0
        )

    if (
        not name
        or not token
        or price <= 0
    ):

        return await q.edit_message_text(
            "❌ Buyurtma maʼlumotlari eskirgan."
        )

    current_balance = balance_of(uid)

    if current_balance < price:

        return await q.edit_message_text(
            f"❌ Balans yetarli emas.\n\n"
            f"Kerak: {price:,.0f} so‘m\n"
            f"Balans: {current_balance:,.0f} so‘m"
        )

    change_balance(
        uid,
        -price
    )

    try:

        if stars:

            r = await asyncio.to_thread(
                buy_stars,
                name,
                qty,
                token
            )

            order_type = "stars"

        else:

            r = await asyncio.to_thread(
                buy_premium,
                name,
                months,
                token
            )

            order_type = "premium"

        oid = str(
            r.get("order_id", "")
        )

        raw_status = str(
            r.get(
                "status",
                "processing"
            )
        )

        if not oid:
            raise Exception(
                "Order ID olinmadi"
            )

        execute("""
            INSERT INTO orders(
                user_id,
                provider_order_id,
                order_type,
                username,
                quantity,
                months,
                provider_cost,
                sell_price,
                status,
                created_at,
                updated_at
            )
            VALUES(
                %s,%s,%s,%s,%s,%s,
                0,%s,%s,%s,%s
            )
        """, (
            uid,
            oid,
            order_type,
            name,
            qty,
            months,
            price,
            raw_status,
            now(),
            now()
        ))

        if successful_status(raw_status):

            success_text = (
                "✅ <b>Buyurtma muvaffaqiyatli bajarildi!</b>\n\n"
                f"📦 ID: <code>{oid}</code>\n"
                f"👤 @{name}\n"
            )

            if stars:
                success_text += (
                    f"⭐ Stars: {qty}\n"
                )
            else:
                success_text += (
                    f"💎 Premium: {months} oy\n"
                )

            success_text += (
                f"💰 To‘lov: {price:,.0f} so‘m\n"
                "\n🎉 Xizmatingiz muvaffaqiyatli bajarildi!"
            )

        else:

            success_text = (
                "✅ <b>Buyurtma qabul qilindi!</b>\n\n"
                f"📦 ID: <code>{oid}</code>\n"
                f"👤 @{name}\n"
            )

            if stars:
                success_text += (
                    f"⭐ Stars: {qty}\n"
                )
            else:
                success_text += (
                    f"💎 Premium: {months} oy\n"
                )

            success_text += (
                f"💰 {price:,.0f} so‘m\n"
                f"📊 {status_text(raw_status)}"
            )

        await q.edit_message_text(
            success_text,
            parse_mode="HTML"
        )

        c.user_data.clear()

    except Exception:

        log.exception(
            "purchase"
        )

        change_balance(
            uid,
            price
        )

        await q.edit_message_text(
            "❌ Buyurtma bajarilmadi.\n\n"
            "💰 Balansingiz qaytarildi.\n\n"
            "Muammo davom etsa, 🆘 SOS / Admin orqali "
            "administrator bilan bog‘laning."
        )


# =========================================================
# MY ORDERS
# =========================================================

async def my_orders(u, c):

    rows = fetchall(
        """
        SELECT *
        FROM orders
        WHERE user_id=%s
        ORDER BY id DESC
        LIMIT 10
        """,
        (u.effective_user.id,)
    )

    if not rows:

        return await u.message.reply_text(
            "📦 Sizda hali buyurtmalar yo‘q."
        )

    s = (
        "📦 <b>Buyurtmalar</b>\n\n"
    )

    for r in rows:

        s += (
            f"🆔 <code>{r['provider_order_id']}</code>\n"
            f"📦 {r['order_type']}\n"
            f"👤 @{r['username']}\n"
            f"💰 {float(r['sell_price']):,.0f} so‘m\n"
            f"📊 {status_text(r['status'])}\n"
            f"📅 {r['created_at']}\n\n"
        )

    await u.message.reply_text(
        s,
        parse_mode="HTML"
    )


# =========================================================
# RATING
# =========================================================

async def rating(u, c):

    rows = fetchall("""
        SELECT
            u.username,
            u.first_name,
            COUNT(o.id) orders_count,
            COALESCE(
                SUM(o.sell_price),
                0
            ) spent
        FROM users u
        LEFT JOIN orders o
            ON u.user_id=o.user_id
        GROUP BY u.user_id
        ORDER BY spent DESC
        LIMIT 10
    """)

    s = "🏆 <b>Top</b>\n\n"

    for i, r in enumerate(rows, 1):

        name = (
            "@" + r["username"]
            if r["username"]
            else r["first_name"]
        )

        s += (
            f"{i}. {name} — "
            f"{float(r['spent']):,.0f} so‘m\n"
        )

    await u.message.reply_text(
        s,
        parse_mode="HTML"
    )


# =========================================================
# TOPUP
# =========================================================

async def topup(u, c):

    if fetchone(
        """
        SELECT id
        FROM payments
        WHERE user_id=%s
        AND status='Kutilmoqda'
        ORDER BY id DESC
        LIMIT 1
        """,
        (u.effective_user.id,)
    ):

        return await u.message.reply_text(
            "⏳ Sizda allaqachon tekshirilayotgan "
            "to‘lov bor."
        )

    c.user_data.clear()

    c.user_data[
        "topup_active"
    ] = True

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💳 To‘lov qildim",
                    callback_data="topup_paid"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="topup_cancel"
                )
            ]
        ]
    )

    await u.message.reply_text(
        f"💳 <b>Balans to‘ldirish</b>\n\n"
        f"💳 Karta: <code>{CARD_NUMBER}</code>\n"
        f"👤 Egasi: <b>{CARD_OWNER}</b>\n\n"
        "⬆️ Shu kartaga kerakli summani o‘tkazing.\n"
        "To‘lovdan keyin <b>💳 To‘lov qildim</b> "
        "tugmasini bosing.\n\n"
        "⚠️ Balansga tushadigan summani admin "
        "chekni tekshirgach kiritadi.",
        parse_mode="HTML",
        reply_markup=kb
    )


async def topup_paid(u, c):

    q = u.callback_query

    await q.answer()

    if not c.user_data.get(
        "topup_active"
    ):

        return await q.edit_message_text(
            "❌ Jarayon topilmadi. "
            "Qaytadan boshlang."
        )

    c.user_data[
        "waiting_receipt"
    ] = True

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "❌ Bekor qilish",
                    callback_data="topup_cancel"
                )
            ]
        ]
    )

    await q.edit_message_text(
        "📸 <b>Chekni yuboring</b>\n\n"
        "To‘lov chekini yoki skrinshotini "
        "rasm sifatida yuboring.",
        parse_mode="HTML",
        reply_markup=kb
    )


async def receipt(u, c):

    if not c.user_data.get(
        "waiting_receipt"
    ):
        return

    uid = u.effective_user.id

    p = fetchone(
        """
        SELECT id
        FROM payments
        WHERE user_id=%s
        AND status='Kutilmoqda'
        LIMIT 1
        """,
        (uid,)
    )

    if p:

        return await u.message.reply_text(
            f"⏳ Chek allaqachon yuborilgan.\n"
            f"ID: {p['id']}"
        )

    con = pool.getconn()

    try:

        x = con.cursor()

        x.execute(
            """
            INSERT INTO payments(
                user_id,
                amount,
                status,
                created_at
            )
            VALUES(
                %s,0,'Kutilmoqda',%s
            )
            RETURNING id
            """,
            (
                uid,
                now()
            )
        )

        pid = x.fetchone()[0]

        con.commit()

    except:

        con.rollback()
        raise

    finally:

        pool.putconn(con)

    c.user_data.clear()

    usr = u.effective_user

    un = (
        "@" + usr.username
        if usr.username
        else "Username yo‘q"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Qabul qilish",
                    callback_data=f"payment_approve_{pid}"
                ),
                InlineKeyboardButton(
                    "❌ Rad etish",
                    callback_data=f"payment_reject_{pid}"
                )
            ]
        ]
    )

    cap = (
        "💳 <b>YANGI TO‘LOV</b>\n\n"
        f"🆔 ID: <code>{pid}</code>\n"
        f"👤 User ID: <code>{uid}</code>\n"
        f"👤 {un}\n"
        f"📝 {usr.first_name or 'Nomaʼlum'}\n"
        "💰 Summa: <b>Admin chekdan kiritadi</b>\n"
        "📊 Kutilmoqda\n"
        f"📅 {now()}"
    )

    try:

        await c.bot.send_photo(
            ADMIN_ID,
            u.message.photo[-1].file_id,
            caption=cap,
            parse_mode="HTML",
            reply_markup=kb
        )

    except Exception:

        execute(
            """
            UPDATE payments
            SET status='Xatolik'
            WHERE id=%s
            """,
            (pid,)
        )

        return await u.message.reply_text(
            "❌ Chekni adminga yuborishda xatolik."
        )

    await u.message.reply_text(
        "✅ <b>Chek yuborildi!</b>\n"
        "⏳ Admin tekshiruvini kuting.",
        parse_mode="HTML",
        reply_markup=user_key()
    )


# =========================================================
# ADMIN
# =========================================================

async def admin_stats(u, c):

    r = fetchone("""
        SELECT
            (SELECT COUNT(*) FROM users) users,
            (SELECT COUNT(*) FROM orders) orders,
            (
                SELECT COALESCE(
                    SUM(sell_price),0
                )
                FROM orders
            ) sales,
            (
                SELECT COALESCE(
                    SUM(amount),0
                )
                FROM payments
                WHERE status='Tasdiqlandi'
            ) payments,
            (
                SELECT COALESCE(
                    SUM(balance),0
                )
                FROM users
            ) ub
    """)

    await u.message.reply_text(
        f"📊 <b>Statistika</b>\n\n"
        f"👥 {r['users']}\n"
        f"📦 {r['orders']}\n"
        f"💰 Savdo: {float(r['sales']):,.0f} so‘m\n"
        f"💳 To‘lovlar: {float(r['payments']):,.0f} so‘m\n"
        f"💵 Balanslar: {float(r['ub']):,.0f} so‘m",
        parse_mode="HTML"
    )


async def admin_users(u, c):

    rows = fetchall(
        """
        SELECT *
        FROM users
        ORDER BY joined_at DESC
        LIMIT 30
        """
    )

    s = (
        "👥 <b>Foydalanuvchilar</b>\n\n"
    )

    for r in rows:

        s += (
            f"🆔 <code>{r['user_id']}</code>\n"
            f"👤 @{r['username'] or 'yo‘q'}\n"
            f"💰 {float(r['balance']):,.0f} so‘m\n"
            f"📅 {r['joined_at']}\n\n"
        )

    await u.message.reply_text(
        s,
        parse_mode="HTML"
    )


async def admin_orders(u, c):

    rows = fetchall(
        """
        SELECT *
        FROM orders
        ORDER BY id DESC
        LIMIT 20
        """
    )

    s = (
        "📦 <b>Buyurtmalar</b>\n\n"
    )

    for r in rows:

        s += (
            f"🆔 {r['provider_order_id']}\n"
            f"👤 User {r['user_id']}\n"
            f"📦 {r['order_type']}\n"
            f"💰 {float(r['sell_price']):,.0f}\n"
            f"📊 {status_text(r['status'])}\n\n"
        )

    await u.message.reply_text(
        s,
        parse_mode="HTML"
    )


async def admin_payments(u, c):

    rows = fetchall(
        """
        SELECT *
        FROM payments
        ORDER BY id DESC
        LIMIT 20
        """
    )

    s = (
        "💳 <b>To‘lovlar</b>\n\n"
    )

    for r in rows:

        s += (
            f"🆔 {r['id']}\n"
            f"👤 User {r['user_id']}\n"
            f"💰 {float(r['amount']):,.0f}\n"
            f"📊 {r['status']}\n\n"
        )

    await u.message.reply_text(
        s,
        parse_mode="HTML"
    )


async def paystars_balance(u, c):

    try:

        a = await asyncio.to_thread(
            account
        )

        await u.message.reply_text(
            str(a)
        )

    except Exception:

        await u.message.reply_text(
            "❌ PayStars balansini olishda xatolik."
        )


async def admin_add(u, c, minus=False):

    c.user_data.clear()

    c.user_data[
        "sub_mode" if minus else "add_mode"
    ] = True

    await u.message.reply_text(
        "🆔 Foydalanuvchi ID sini yuboring:"
    )


async def admin_post(u, c):

    c.user_data["post_mode"] = False

    rows = fetchall(
        """
        SELECT user_id
        FROM users
        WHERE is_active=1
        """
    )

    ok = 0

    for r in rows:

        try:

            await c.bot.send_message(
                r["user_id"],
                u.message.text
            )

            ok += 1

            await asyncio.sleep(
                0.05
            )

        except:
            pass

    await u.message.reply_text(
        f"📢 Yetkazildi: {ok}"
    )


async def admin_amount(u, c):

    if u.effective_user.id != ADMIN_ID:
        return False

    t = (
        u.message.text
        .strip()
        .replace(" ", "")
        .replace(",", "")
    )

    if c.user_data.get(
        "payment_approve"
    ):

        try:

            a = float(t)

            assert a > 0

        except:

            await u.message.reply_text(
                "❌ To‘g‘ri summa yozing."
            )

            return True

        pid = c.user_data[
            "payment_approve"
        ]

        con = pool.getconn()

        try:

            x = con.cursor()

            x.execute(
                """
                SELECT *
                FROM payments
                WHERE id=%s
                FOR UPDATE
                """,
                (pid,)
            )

            raw = x.fetchone()

            if not raw:

                con.rollback()

                await u.message.reply_text(
                    "❌ To‘lov topilmadi."
                )

                return True

            cols = [
                d[0]
                for d in x.description
            ]

            p = dict(
                zip(cols, raw)
            )

            if p["status"] != "Kutilmoqda":

                con.rollback()

                c.user_data.clear()

                await u.message.reply_text(
                    "❌ Allaqachon ko‘rib chiqilgan."
                )

                return True

            x.execute(
                """
                UPDATE users
                SET balance=balance+%s
                WHERE user_id=%s
                """,
                (
                    a,
                    p["user_id"]
                )
            )

            x.execute(
                """
                UPDATE payments
                SET
                    amount=%s,
                    status='Tasdiqlandi',
                    approved_at=%s,
                    admin_id=%s
                WHERE id=%s
                """,
                (
                    a,
                    now(),
                    ADMIN_ID,
                    pid
                )
            )

            con.commit()

        except:

            con.rollback()

            log.exception(
                "approve"
            )

            await u.message.reply_text(
                "❌ Tasdiqlashda xatolik."
            )

            return True

        finally:

            pool.putconn(con)

        c.user_data.clear()

        nb = balance_of(
            p["user_id"]
        )

        try:

            await c.bot.send_message(
                p["user_id"],
                f"✅ <b>To‘lov tasdiqlandi!</b>\n\n"
                f"💰 +{a:,.0f} so‘m\n"
                f"💳 Yangi balans: {nb:,.0f} so‘m",
                parse_mode="HTML"
            )

        except:
            pass

        await u.message.reply_text(
            f"✅ To‘lov #{pid} tasdiqlandi.\n"
            f"+{a:,.0f} so‘m"
        )

        return True

    if (
        c.user_data.get("add_amount")
        or c.user_data.get("sub_amount")
    ):

        try:

            a = float(t)

            assert a > 0

        except:

            await u.message.reply_text(
                "❌ Summa noto‘g‘ri."
            )

            return True

        uid = c.user_data[
            "amount_uid"
        ]

        minus = c.user_data.get(
            "sub_amount"
        )

        if minus and balance_of(uid) < a:

            await u.message.reply_text(
                "❌ Balans yetarli emas."
            )

            return True

        change_balance(
            uid,
            -a if minus else a
        )

        c.user_data.clear()

        await u.message.reply_text(
            f"✅ {uid} balansiga "
            f"{a:,.0f} so‘m "
            + (
                "ayirildi."
                if minus
                else "qo‘shildi."
            )
        )

        return True

    return False


# =========================================================
# PROMO
# =========================================================

async def promo_menu(u, c):

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Yaratish",
                    callback_data="promo_create"
                )
            ],
            [
                InlineKeyboardButton(
                    "📋 Ro‘yxat",
                    callback_data="promo_list"
                )
            ],
            [
                InlineKeyboardButton(
                    "🗑 O‘chirish",
                    callback_data="promo_delete"
                )
            ]
        ]
    )

    await u.message.reply_text(
        "🎁 <b>Promokod</b>",
        parse_mode="HTML",
        reply_markup=kb
    )


async def promo_cb(u, c):

    q = u.callback_query

    if q.from_user.id != ADMIN_ID:

        return await q.answer(
            "❌ Ruxsat yo‘q",
            show_alert=True
        )

    await q.answer()

    if q.data == "promo_create":

        c.user_data.clear()

        c.user_data[
            "pc_code"
        ] = True

        return await q.message.reply_text(
            "🎟 Kodni yuboring:"
        )

    if q.data == "promo_delete":

        c.user_data.clear()

        c.user_data[
            "pc_delete"
        ] = True

        return await q.message.reply_text(
            "🗑 O‘chiriladigan kodni yuboring:"
        )

    rows = fetchall(
        """
        SELECT *
        FROM promocodes
        ORDER BY created_at DESC
        """
    )

    s = (
        "🎁 <b>Promokodlar</b>\n\n"
    )

    for r in rows:

        s += (
            f"{r['code']} — "
            f"{float(r['amount']):,.0f} — "
            f"{r['used_count']}/"
            f"{r['limit_count']}\n"
        )

    await q.message.reply_text(
        s if rows else "Promokodlar yo‘q.",
        parse_mode="HTML"
    )


async def promo_text(u, c):

    if u.effective_user.id != ADMIN_ID:
        return False

    t = u.message.text.strip()

    if c.user_data.get(
        "pc_code"
    ):

        c.user_data = {
            "pc_amount": True,
            "new_code": t.upper()
        }

        await u.message.reply_text(
            "💰 Summani yuboring:"
        )

        return True

    if c.user_data.get(
        "pc_amount"
    ):

        try:

            a = float(t)

            assert a > 0

        except:

            await u.message.reply_text(
                "❌ Summa noto‘g‘ri."
            )

            return True

        c.user_data[
            "pc_amount"
        ] = False

        c.user_data[
            "pc_limit"
        ] = True

        c.user_data[
            "new_amount"
        ] = a

        await u.message.reply_text(
            "👥 Limitni yuboring:"
        )

        return True

    if c.user_data.get(
        "pc_limit"
    ):

        try:

            l = int(t)

            assert l > 0

        except:

            await u.message.reply_text(
                "❌ Limit noto‘g‘ri."
            )

            return True

        execute(
            """
            INSERT INTO promocodes(
                code,
                amount,
                limit_count,
                used_count,
                created_at
            )
            VALUES(
                %s,%s,%s,0,%s
            )
            ON CONFLICT(code)
            DO UPDATE SET
                amount=EXCLUDED.amount,
                limit_count=EXCLUDED.limit_count,
                used_count=0,
                created_at=EXCLUDED.created_at
            """,
            (
                c.user_data["new_code"],
                c.user_data["new_amount"],
                l,
                now()
            )
        )

        c.user_data.clear()

        await u.message.reply_text(
            "✅ Promokod yaratildi."
        )

        return True

    if c.user_data.get(
        "pc_delete"
    ):

        n = execute(
            """
            DELETE FROM promocodes
            WHERE code=%s
            """,
            (t.upper(),)
        )

        c.user_data.clear()

        await u.message.reply_text(
            "✅ O‘chirildi."
            if n
            else "❌ Topilmadi."
        )

        return True

    return False


# =========================================================
# ROUTER
# =========================================================

async def route(u, c):

    register(
        u.effective_user
    )

    t = u.message.text

    if (
        t in USER_MENU
        or (
            u.effective_user.id == ADMIN_ID
            and t in ADMIN_MENU
        )
    ):

        c.user_data.clear()

        if t == "🛍️ Buyurtma berish":
            return await catalog(u, c)

        if t == "💳 Balans to‘ldirish":
            return await topup(u, c)

        if t == "💰 Balans":
            return await balance(u, c)

        if t == "📦 Buyurtmalarim":
            return await my_orders(u, c)

        if t == "👤 Profil":
            return await profile(u, c)

        if t == "🏆 Reyting":
            return await rating(u, c)

        if t == "🆘 SOS / Admin":
            return await sos(u, c)

        if t == "🎁 Promokod":

            if u.effective_user.id == ADMIN_ID:
                return await promo_menu(u, c)

            c.user_data[
                "waiting_promo"
            ] = True

            return await u.message.reply_text(
                "🎁 Promokodni yuboring:"
            )

        if t == "👥 Foydalanuvchilar":
            return await admin_users(u, c)

        if t == "📊 Statistika":
            return await admin_stats(u, c)

        if t == "📦 Buyurtmalar":
            return await admin_orders(u, c)

        if t == "💳 To‘lovlar":
            return await admin_payments(u, c)

        # =================================================
        # FAQAT SHU QISM TUZATILDI
        # PAYSTARS API BALANSI
        # =================================================

        if t == "💰 PayStars balansi":

            try:

                a = await asyncio.to_thread(
                    account
                )

                balance = a.get(
                    "user",
                    {}
                ).get(
                    "balance",
                    0
                )

                return await u.message.reply_text(
                    f"💰 <b>PayStars API balansi</b>\n\n"
                    f"💵 Balans: <b>{balance:,.0f} so‘m</b>",
                    parse_mode="HTML"
                )

            except:

                return await u.message.reply_text(
                    "❌ PayStars balansini olishda xatolik."
                )

        if t == "🔄 Katalog":

            try:

                return await u.message.reply_text(
                    str(
                        await asyncio.to_thread(
                            prices
                        )
                    )
                )

            except:

                return await u.message.reply_text(
                    "❌ Katalog xatosi."
                )

        if t == "💰 Pul +":

            c.user_data[
                "add_mode"
            ] = True

            return await u.message.reply_text(
                "🆔 User ID:"
            )

        if t == "💸 Pul −":

            c.user_data[
                "sub_mode"
            ] = True

            return await u.message.reply_text(
                "🆔 User ID:"
            )

        if t == "📢 Post":

            c.user_data[
                "post_mode"
            ] = True

            return await u.message.reply_text(
                "📢 Xabarni yuboring:"
            )

        if t == "❌ Admin paneldan chiqish":

            return await u.message.reply_text(
                "Admin panel yopildi.",
                reply_markup=user_key()
            )

    # Premium username
    if c.user_data.get(
        "waiting_premium_username"
    ):

        return await premium_username(
            u,
            c
        )

    # Promo
    if c.user_data.get(
        "waiting_promo"
    ):

        code = t.upper()

        c.user_data.clear()

        r = fetchone(
            """
            SELECT *
            FROM promocodes
            WHERE code=%s
            """,
            (code,)
        )

        if not r:

            return await u.message.reply_text(
                "❌ Promokod topilmadi."
            )

        if (
            r["used_count"]
            >= r["limit_count"]
            or fetchone(
                """
                SELECT 1
                FROM promo_uses
                WHERE user_id=%s
                AND code=%s
                """,
                (
                    u.effective_user.id,
                    code
                )
            )
        ):

            return await u.message.reply_text(
                "❌ Promokod ishlamaydi "
                "yoki avval ishlatilgan."
            )

        con = pool.getconn()

        try:

            x = con.cursor()

            x.execute(
                """
                INSERT INTO promo_uses
                VALUES(%s,%s,%s)
                """,
                (
                    u.effective_user.id,
                    code,
                    now()
                )
            )

            x.execute(
                """
                UPDATE promocodes
                SET used_count=used_count+1
                WHERE code=%s
                """,
                (code,)
            )

            x.execute(
                """
                UPDATE users
                SET balance=balance+%s
                WHERE user_id=%s
                """,
                (
                    float(r["amount"]),
                    u.effective_user.id
                )
            )

            con.commit()

        except:

            con.rollback()
            raise

        finally:

            pool.putconn(con)

        return await u.message.reply_text(
            f"🎉 +{float(r['amount']):,.0f} "
            "so‘m qo‘shildi!"
        )

    # Admin balance
    if u.effective_user.id == ADMIN_ID:

        if (
            c.user_data.get("add_mode")
            or c.user_data.get("sub_mode")
        ):

            try:

                uid = int(t)

                assert fetchone(
                    "SELECT 1 FROM users WHERE user_id=%s",
                    (uid,)
                )

            except:

                return await u.message.reply_text(
                    "❌ User ID topilmadi."
                )

            minus = c.user_data.get(
                "sub_mode"
            )

            c.user_data.clear()

            c.user_data[
                "amount_uid"
            ] = uid

            c.user_data[
                "sub_amount"
                if minus
                else "add_amount"
            ] = True

            return await u.message.reply_text(
                "💰 Summani yuboring:"
            )

        if c.user_data.get(
            "post_mode"
        ):

            return await admin_post(
                u,
                c
            )


# =========================================================
# TEXT HANDLER
# =========================================================

async def text_handler(u, c):

    if u.effective_user.id == ADMIN_ID:

        if await admin_amount(u, c):
            return

        if await promo_text(u, c):
            return

    await route(u, c)


# =========================================================
# PAYMENT CALLBACK
# =========================================================

async def payment_cb(u, c):

    q = u.callback_query

    if q.from_user.id != ADMIN_ID:

        return await q.answer(
            "❌ Ruxsat yo‘q",
            show_alert=True
        )

    await q.answer()

    pid = int(
        q.data.rsplit("_", 1)[1]
    )

    p = fetchone(
        """
        SELECT *
        FROM payments
        WHERE id=%s
        """,
        (pid,)
    )

    if (
        not p
        or p["status"] != "Kutilmoqda"
    ):

        return await q.answer(
            "❌ To‘lov allaqachon ko‘rilgan.",
            show_alert=True
        )

    if q.data.startswith(
        "payment_approve_"
    ):

        c.user_data.clear()

        c.user_data[
            "payment_approve"
        ] = pid

        await q.message.reply_text(
            f"💰 <b>Qancha balans qo‘shamiz?</b>\n\n"
            f"🆔 {pid}\n"
            f"👤 User: {p['user_id']}\n\n"
            "Chekdagi summani yozing:",
            parse_mode="HTML"
        )

        try:

            await q.edit_message_caption(
                caption=(
                    "➕ <b>QABUL QILINDI</b>\n\n"
                    f"🆔 {pid}\n"
                    "⏳ Summa kutilmoqda"
                ),
                parse_mode="HTML",
                reply_markup=None
            )

        except:
            pass

    else:

        execute(
            """
            UPDATE payments
            SET
                status='Rad etildi',
                admin_id=%s,
                approved_at=%s
            WHERE id=%s
            """,
            (
                ADMIN_ID,
                now(),
                pid
            )
        )

        try:

            await c.bot.send_message(
                p["user_id"],
                f"❌ To‘lov #{pid} rad etildi."
            )

        except:
            pass

        try:

            await q.edit_message_caption(
                caption=(
                    "❌ <b>RAD ETILDI</b>\n\n"
                    f"🆔 {pid}"
                ),
                parse_mode="HTML"
            )

        except:
            pass


# =========================================================
# CALLBACK
# =========================================================

async def callback(u, c):

    d = (
        u.callback_query.data
        or ""
    )

    if d.startswith("payment_"):
        return await payment_cb(u, c)

    if d in (
        "confirm_stars",
        "confirm_premium"
    ):

        return await confirm(u, c)

    q = u.callback_query

    await q.answer()

    if d == "topup_paid":
        return await topup_paid(u, c)

    if d == "topup_cancel":

        c.user_data.clear()

        return await q.edit_message_text(
            "❌ Balans to‘ldirish bekor qilindi."
        )

    if d == "cancel_order":

        c.user_data.clear()

        return await q.edit_message_text(
            "❌ Buyurtma bekor qilindi."
        )

    if d == "buy_premium":

        return await premium_start(
            u,
            c
        )

    if d.startswith(
        "premium_month_"
    ):

        return await premium_month(
            u,
            c
        )

    if d == "close":

        c.user_data.clear()

        try:
            await q.message.delete()
        except:
            pass

        return

    if d.startswith("promo_"):

        return await promo_cb(
            u,
            c
        )


# =========================================================
# ERROR
# =========================================================

async def error(u, c):

    log.error(
        "BOT ERROR",
        exc_info=c.error
    )


# =========================================================
# RUN
# =========================================================

def main():

    init_db()

    missing = [
        x
        for x, v in [
            ("BOT_TOKEN", BOT_TOKEN),
            ("PAYSTARS_API_KEY", PAYSTARS_API_KEY),
            ("DATABASE_URL", DATABASE_URL)
        ]
        if not v
    ]

    if not ADMIN_ID:
        missing.append(
            "ADMIN_ID"
        )

    if not RENDER_EXTERNAL_URL:

        raise RuntimeError(
            "RENDER_EXTERNAL_URL topilmadi. "
            "Render Web Service kerak."
        )

    if missing:

        raise RuntimeError(
            "Yetishmayapti: "
            + ", ".join(missing)
        )

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # START
    app.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # ADMIN
    app.add_handler(
        CommandHandler(
            "admin",
            admin_cmd
        )
    )

    # MENU FILTER
    menu_filter = filters.Regex(
        r"^(🛍️ Buyurtma berish|"
        r"💳 Balans to‘ldirish|"
        r"💰 Balans|"
        r"📦 Buyurtmalarim|"
        r"🎁 Promokod|"
        r"👤 Profil|"
        r"🏆 Reyting|"
        r"🆘 SOS / Admin|"
        r"💰 Pul \+|"
        r"💸 Pul −|"
        r"💳 To‘lovlar|"
        r"📊 Statistika|"
        r"👥 Foydalanuvchilar|"
        r"📦 Buyurtmalar|"
        r"📢 Post|"
        r"🔄 Katalog|"
        r"💰 PayStars balansi|"
        r"❌ Admin paneldan chiqish)$"
    )

    # STARS CONVERSATION
    app.add_handler(
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    stars_start,
                    pattern=r"^buy_stars$"
                )
            ],
            states={
                SU: [
                    MessageHandler(
                        menu_filter,
                        stars_fallback
                    ),
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        stars_username
                    )
                ],
                SQ: [
                    MessageHandler(
                        menu_filter,
                        stars_fallback
                    ),
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        stars_quantity
                    )
                ]
            },
            fallbacks=[
                MessageHandler(
                    menu_filter,
                    stars_fallback
                )
            ],
            per_user=True,
            per_chat=True
        )
    )

    # PAYMENT
    app.add_handler(
        CallbackQueryHandler(
            payment_cb,
            pattern=r"^payment_(approve|reject)_\d+$"
        )
    )

    # ALL CALLBACKS
    app.add_handler(
        CallbackQueryHandler(
            callback
        )
    )

    # RECEIPT
    app.add_handler(
        MessageHandler(
            filters.PHOTO,
            receipt
        )
    )

    # TEXT
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            text_handler
        )
    )

    app.add_error_handler(
        error
    )

    url = (
        f"{RENDER_EXTERNAL_URL}/"
        f"{BOT_TOKEN}"
    )

    print(
        "================================"
    )

    print(
        "PAYSTARS BOT RENDER WEBHOOK ISHGA TUSHDI"
    )

    print(
        "================================"
    )

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        url_path=BOT_TOKEN,
        webhook_url=url,
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
