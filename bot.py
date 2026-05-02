import logging
import cv2
import numpy as np
from io import BytesIO
from PIL import Image
import json
import os

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ============================
# НАСТРОЙКИ — ЗАПОЛНИ ЗДЕСЬ
# ============================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = 6672393699
# ============================

logging.basicConfig(level=logging.INFO)

USERS_FILE = "users.json"
CHANNELS_FILE = "channels.json"


# ── Хранилище ──────────────────────────────────────────────

def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_users(users):
    with open(USERS_FILE, "w") as f:
        json.dump(list(users), f)

def load_channels():
    if os.path.exists(CHANNELS_FILE):
        with open(CHANNELS_FILE, "r") as f:
            return json.load(f)
    return []

def save_channels(channels):
    with open(CHANNELS_FILE, "w") as f:
        json.dump(channels, f)

all_users = load_users()
required_channels = load_channels()

# Состояния
waiting_for_photo = set()
waiting_for_broadcast = set()
waiting_for_channel = set()


# ── Проверка подписок ───────────────────────────────────────

async def check_subscriptions(user_id: int, bot) -> list:
    """Возвращает список каналов на которые пользователь НЕ подписан"""
    not_subscribed = []
    for ch in required_channels:
        try:
            member = await bot.get_chat_member(ch["id"], user_id)
            if member.status in ("left", "kicked"):
                not_subscribed.append(ch)
        except Exception:
            not_subscribed.append(ch)
    return not_subscribed


def build_subscribe_keyboard(channels: list) -> InlineKeyboardMarkup:
    buttons = []
    for ch in channels:
        buttons.append([InlineKeyboardButton(f"📢 {ch['username']}", url=f"https://t.me/{ch['username'].lstrip('@')}")])
    buttons.append([InlineKeyboardButton("✅ Я подписался", callback_data="check_sub")])
    return InlineKeyboardMarkup(buttons)


# ── /start ──────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    all_users.add(user_id)
    save_users(all_users)

    keyboard = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Пиксельное лицо")]],
        resize_keyboard=True
    )
    await update.message.reply_text("Привет, вы в нашем боте JanerShop 👋")
    await update.message.reply_text("Выберите действие снизу!", reply_markup=keyboard)


# ── Главное меню ────────────────────────────────────────────

async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    user_id = update.message.from_user.id

    if text == "📍 Пиксельное лицо":
        not_subbed = await check_subscriptions(user_id, context.bot)
        if not_subbed:
            await update.message.reply_text(
                "❗ Чтобы использовать эту функцию, подпишись на наши каналы:",
                reply_markup=build_subscribe_keyboard(not_subbed)
            )
            return
        waiting_for_photo.add(user_id)
        await update.message.reply_text("Скиньте фотографию 📸")
        await update.message.reply_text("🔴 Обведите красным цветом те места которые нужно сделать пиксельными!")


# ── Callback кнопки ─────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "check_sub":
        not_subbed = await check_subscriptions(user_id, context.bot)
        if not_subbed:
            await query.message.edit_text(
                "❗ Ты ещё не подписался на все каналы:",
                reply_markup=build_subscribe_keyboard(not_subbed)
            )
        else:
            await query.message.delete()
            waiting_for_photo.add(user_id)
            await context.bot.send_message(user_id, "✅ Отлично! Теперь скиньте фотографию 📸")

    elif data == "admin_broadcast":
        waiting_for_broadcast.add(user_id)
        await query.message.edit_text("✍️ Напишите сообщение для рассылки всем пользователям бота:")

    elif data == "admin_add_channel":
        waiting_for_channel.add(user_id)
        await query.message.edit_text(
            "📢 Скиньте юзернейм канала (например @mychannel):\n\n"
            "⚠️ Убедитесь что бот добавлен в канал как администратор!"
        )

    elif data == "admin_remove_channel":
        channels = load_channels()
        if not channels:
            await query.message.edit_text("❌ Обязательных каналов нет.")
            return
        buttons = []
        for ch in channels:
            buttons.append([InlineKeyboardButton(f"❌ Удалить {ch['username']}", callback_data=f"del_ch_{ch['id']}")])
        buttons.append([InlineKeyboardButton("◀️ Назад", callback_data="back_admin")])
        await query.message.edit_text(
            "Выберите канал для удаления из обязательных подписок:",
            reply_markup=InlineKeyboardMarkup(buttons)
        )

    elif data.startswith("del_ch_"):
        ch_id = data.replace("del_ch_", "")
        channels = load_channels()
        channels = [c for c in channels if str(c["id"]) != ch_id]
        save_channels(channels)
        global required_channels
        required_channels = channels
        await query.message.edit_text("✅ Канал удалён из обязательных подписок!")

    elif data == "back_admin":
        await show_admin_panel(query.message, edit=True)


async def show_admin_panel(message, edit=False):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📣 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("➕ Обязательные подписки", callback_data="admin_add_channel")],
        [InlineKeyboardButton("➖ Убрать обязательный канал", callback_data="admin_remove_channel")],
    ])
    text = "👑 Панель администратора\n\nВыберите действие:"
    if edit:
        await message.edit_text(text, reply_markup=keyboard)
    else:
        await message.reply_text(text, reply_markup=keyboard)


# ── /admin ──────────────────────────────────────────────────

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.from_user.id != ADMIN_ID:
        await update.message.reply_text("❌ У вас нет доступа.")
        return
    await show_admin_panel(update.message)


# ── Текстовые сообщения ──────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    text = update.message.text

    # Рассылка (только для админа)
    if user_id in waiting_for_broadcast and user_id == ADMIN_ID:
        waiting_for_broadcast.discard(user_id)
        users = load_users()  # Всегда читаем свежий список
        success = 0
        failed = 0
        for uid in users:
            try:
                await context.bot.send_message(int(uid), text)
                success += 1
            except Exception as e:
                logging.warning(f"Не удалось отправить {uid}: {e}")
                failed += 1
        await update.message.reply_text(
            f"✅ Рассылка завершена!\n"
            f"📨 Отправлено: {success}\n"
            f"❌ Не доставлено: {failed}"
        )
        return

    # Добавление канала (только для админа)
    if user_id in waiting_for_channel and user_id == ADMIN_ID:
        waiting_for_channel.discard(user_id)
        username = text.strip()
        if not username.startswith("@"):
            username = "@" + username
        try:
            chat = await context.bot.get_chat(username)
            channels = load_channels()
            if any(c["id"] == str(chat.id) for c in channels):
                await update.message.reply_text("⚠️ Этот канал уже в списке обязательных.")
                return
            channels.append({"id": str(chat.id), "username": username})
            save_channels(channels)
            global required_channels
            required_channels = channels
            await update.message.reply_text(f"✅ Канал {username} добавлен в обязательные подписки!")
        except Exception as e:
            await update.message.reply_text(
                f"❌ Не удалось найти канал {username}.\n"
                f"Убедитесь что бот добавлен в канал как администратор.\n\nОшибка: {e}"
            )
        return

    # Обычное меню
    await handle_menu(update, context)


# ── Обработка фото ───────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if user_id not in waiting_for_photo:
        await update.message.reply_text("Сначала нажмите кнопку 🎭 Пиксельное лицо")
        return

    waiting_for_photo.discard(user_id)
    await update.message.reply_text("⏳ Обрабатываю фото...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    file_bytes = await file.download_as_bytearray()

    np_arr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

    # Ищем красные области на фото
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask1 = cv2.inRange(hsv, np.array([0, 120, 100]), np.array([8, 255, 255]))
    mask2 = cv2.inRange(hsv, np.array([165, 120, 100]), np.array([180, 255, 255]))
    red_mask = cv2.bitwise_or(mask1, mask2)

    # Сначала убираем красный со всего фото
    inpaint_kernel = np.ones((5, 5), np.uint8)
    red_for_inpaint = cv2.dilate(red_mask, inpaint_kernel, iterations=2)
    img = cv2.inpaint(img, red_for_inpaint, 5, cv2.INPAINT_TELEA)

    # Находим контуры обводки
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contours = [c for c in contours if cv2.contourArea(c) > 1000]

    fallback = False
    if not contours:
        face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = cv2.equalizeHist(gray)
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(20, 20))
        if len(faces) == 0:
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.03, minNeighbors=2, minSize=(15, 15))
        if len(faces) == 0:
            faces = face_cascade.detectMultiScale(gray, scaleFactor=1.02, minNeighbors=1, minSize=(10, 10))
        if len(faces) == 0:
            h_img, w_img = img.shape[:2]
            faces = [(w_img // 4, h_img // 4, w_img // 2, h_img // 2)]
            fallback = True
        regions = [(x, y, w, h) for (x, y, w, h) in faces]
    else:
        # Заполняем контур изнутри чтобы получить только нужную область
        regions = []
        for c in contours:
            filled_mask = np.zeros(red_mask.shape, dtype=np.uint8)
            cv2.drawContours(filled_mask, [c], -1, 255, thickness=cv2.FILLED)
            fx, fy, fw, fh = cv2.boundingRect(c)
            regions.append((fx, fy, fw, fh))

    for (x, y, w, h) in regions:
        region = img[y:y+h, x:x+w].copy()
        pixel_size = 18
        small = cv2.resize(
            region,
            (max(1, w // pixel_size), max(1, h // pixel_size)),
            interpolation=cv2.INTER_LINEAR
        )
        pixelated = cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST)
        blended = cv2.addWeighted(region, 0.15, pixelated, 0.85, 0)
        img[y:y+h, x:x+w] = blended

    pil_img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    output = BytesIO()
    pil_img.save(output, format="JPEG", quality=95)
    output.seek(0)

    caption = "Готово! 🎭✅"
    if fallback:
        caption = "⚠️ Красных областей не найдено и лицо не определено — пикселизировал центр фото.\n\nГотово! 🎭✅"
    elif not contours:
        caption = "🔍 Красных областей не найдено — пикселизировал лицо автоматически.\n\nГотово! 🎭✅"

    await update.message.reply_document(
        document=output,
        filename="pixelated_face.jpg",
        caption=caption
    )


# ── Запуск ───────────────────────────────────────────────────

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()
