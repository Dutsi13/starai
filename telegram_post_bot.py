import json
import logging
from pathlib import Path
from typing import Dict, List, Tuple

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    MessageEntity,
    Update,
)
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# ===== CONFIG (edit here) =====
BOT_TOKEN = "8517096384:AAEE8Kr7gCs6MVntniQK1u9T6YQajlgnVP4"
ADMIN_IDS = [7785932103]  # add your Telegram user IDs
STATE_FILE = Path("bot_state.json")

# One-time forever contribution in Telegram Stars (XTR)
ONE_TIME_CONTRIBUTION_XTR = 1

ASK_CHAT_ID, ASK_TEXT, ASK_MEDIA, ASK_BUTTONS, ASK_STICKER, CONFIRM = range(6)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

state = {
    "price_standard": ONE_TIME_CONTRIBUTION_XTR,
    "price_premium": ONE_TIME_CONTRIBUTION_XTR,
    "premium_user_ids": [],
    "paid_user_ids": [],
}


def load_state() -> None:
    global state
    if not STATE_FILE.exists():
        save_state()
        return
    try:
        loaded = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state["price_standard"] = ONE_TIME_CONTRIBUTION_XTR
        state["price_premium"] = ONE_TIME_CONTRIBUTION_XTR
        state["premium_user_ids"] = [int(x) for x in loaded.get("premium_user_ids", [])]
        state["paid_user_ids"] = [int(x) for x in loaded.get("paid_user_ids", [])]
    except Exception:
        logger.exception("Failed to load state; using defaults")
        save_state()


def save_state() -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def is_premium(user_id: int) -> bool:
    return user_id in state["premium_user_ids"]


def is_paid(user_id: int) -> bool:
    return user_id in state["paid_user_ids"] or is_admin(user_id)


def current_price(user_id: int) -> int:
    return ONE_TIME_CONTRIBUTION_XTR


def parse_buttons(raw: str) -> Tuple[List[List[InlineKeyboardButton]], List[str]]:
    errors: List[str] = []
    rows_map: Dict[int, Dict[int, InlineKeyboardButton]] = {}
    cleaned = raw.strip()
    if not cleaned or cleaned == "-":
        return [], errors

    sequential_row = 1
    for idx, line in enumerate(cleaned.splitlines(), start=1):
        parts = [p.strip().strip("`").strip() for p in line.split("|")]
        if len(parts) == 2:
            text, url = parts
            row_num, col_num = sequential_row, 1
            sequential_row += 1
        elif len(parts) == 3:
            pos, text, url = parts
            if "," not in pos:
                errors.append(f"Line {idx}: position format must be row,col")
                continue
            row_str, col_str = [x.strip() for x in pos.split(",", 1)]
            if not row_str.isdigit() or not col_str.isdigit():
                errors.append(f"Line {idx}: row and col must be integers")
                continue
            row_num, col_num = int(row_str), int(col_str)
            if row_num < 1 or col_num < 1:
                errors.append(f"Line {idx}: row and col must be >= 1")
                continue
        else:
            errors.append(f"Line {idx}: use 'text|url' or 'row,col|text|url'")
            continue

        text = text.strip().strip("`").strip()
        url = url.strip().strip("`").strip()

        if not text:
            errors.append(f"Line {idx}: empty button text")
            continue
        if not (url.startswith("http://") or url.startswith("https://")):
            errors.append(f"Line {idx}: url must start with http:// or https://")
            continue

        if row_num not in rows_map:
            rows_map[row_num] = {}
        if col_num in rows_map[row_num]:
            errors.append(f"Line {idx}: place {row_num},{col_num} is already used")
            continue
        rows_map[row_num][col_num] = InlineKeyboardButton(text=text, url=url)

    rows: List[List[InlineKeyboardButton]] = []
    for row_num in sorted(rows_map):
        row_buttons: List[InlineKeyboardButton] = []
        for col_num in sorted(rows_map[row_num]):
            row_buttons.append(rows_map[row_num][col_num])
        rows.append(row_buttons)
    return rows, errors


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Unhandled exception while processing update", exc_info=context.error)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_paid(user_id):
        await update.message.reply_text(
            "👋 Привет!\n"
            "Для использования нужен единоразовый взнос 1 ⭐ навсегда.\n"
            "Отправляю счёт ниже."
        )
        await send_contribution_invoice(update, context)
        return

    await update.message.reply_text(
        "👋 Привет! Доступ уже активен ✅\n\n"
        "📌 Команды:\n"
        "/newpost - создать пост\n"
        "/status - твой статус\n"
        "/cancel - отменить текущий шаг"
    )


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(
        f"👤 ID: {user_id}\n"
        f"⭐ Premium user: {'yes' if is_premium(user_id) else 'no'}\n"
        f"✅ Access paid: {'yes' if is_paid(user_id) else 'no'}\n"
        f"💰 One-time contribution: {ONE_TIME_CONTRIBUTION_XTR} XTR"
    )


async def pay_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if is_paid(user_id):
        await update.message.reply_text("✅ У тебя уже есть доступ.")
        return

    await send_contribution_invoice(update, context)


async def send_contribution_invoice(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await context.bot.send_invoice(
        chat_id=update.effective_chat.id,
        title="Взнос за доступ",
        description="Единоразовый взнос 1 ⭐. Доступ к боту навсегда.",
        payload=f"post_access:{update.effective_user.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="One-time contribution", amount=ONE_TIME_CONTRIBUTION_XTR)],
        start_parameter="post-access-forever",
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    if not query.invoice_payload.startswith("post_access:"):
        await query.answer(ok=False, error_message="Invalid payload.")
        return
    await query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in state["paid_user_ids"]:
        state["paid_user_ids"].append(user_id)
        save_state()
    await update.message.reply_text("🎉 Оплата прошла успешно. Доступ открыт. Используй /newpost")


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("🛑 Операция отменена.")
    return ConversationHandler.END


async def new_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if not is_paid(user_id):
        await update.message.reply_text(
            f"🔒 Доступ закрыт.\nОплати {current_price(user_id)} XTR через /pay"
        )
        return ConversationHandler.END

    context.user_data.clear()
    await update.message.reply_text(
        "🧩 Шаг 1/5\n"
        "Введи chat_id, куда отправить пост.\n\n"
        "Примеры:\n"
        "• Канал: -1001234567890\n"
        "• Чат: числовой id"
    )
    return ASK_CHAT_ID


async def ask_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    try:
        chat_id = int(raw)
    except ValueError:
        await update.message.reply_text("❌ chat_id должен быть числом. Попробуй снова.")
        return ASK_CHAT_ID

    context.user_data["chat_id"] = chat_id
    await update.message.reply_text(
        "🧩 Шаг 2/5\n"
        "Отправь основной текст поста.\n"
        "Можно использовать premium emoji прямо в тексте ✨"
    )
    return ASK_TEXT


async def ask_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    post_text = update.message.text
    if not post_text or not post_text.strip():
        await update.message.reply_text("❌ Текст пустой. Отправь текст ещё раз.")
        return ASK_TEXT

    context.user_data["post_text"] = post_text
    context.user_data["post_entities"] = update.message.entities or []
    await update.message.reply_text(
        "🧩 Шаг 3/5\n"
        "Отправь фото для поста 🖼️\n"
        "или отправь `-`, чтобы пропустить."
    )
    return ASK_MEDIA


async def ask_buttons_from_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["photo_file_id"] = update.message.photo[-1].file_id
    await update.message.reply_text(
        "🧩 Шаг 4/5\n"
        "Отправь кнопки:\n\n"
        "Вариант A (где именно ставить кнопку):\n"
        "`1,1 | Каталог | https://example.com`\n"
        "`1,2 | Купить | https://shop.example.com`\n"
        "`2,1 | Поддержка | https://t.me/example`\n\n"
        "Вариант B (простой):\n"
        "`Каталог | https://example.com`\n"
        "`Поддержка | https://t.me/example`\n\n"
        "Или `-` если без кнопок."
    )
    return ASK_BUTTONS


async def ask_buttons_no_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    raw = (update.message.text or "").strip()
    if raw != "-":
        await update.message.reply_text("❌ Отправь фото или `-` чтобы пропустить.")
        return ASK_MEDIA
    context.user_data["photo_file_id"] = None
    return await ask_buttons_from_media_prompt(update, context)


async def ask_buttons_from_media_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    await update.message.reply_text(
        "🧩 Шаг 4/5\n"
        "Отправь кнопки:\n\n"
        "Вариант A (где именно ставить кнопку):\n"
        "`1,1 | Каталог | https://example.com`\n"
        "`1,2 | Купить | https://shop.example.com`\n"
        "`2,1 | Поддержка | https://t.me/example`\n\n"
        "Вариант B (простой):\n"
        "`Каталог | https://example.com`\n"
        "`Поддержка | https://t.me/example`\n\n"
        "Или `-` если без кнопок."
    )
    return ASK_BUTTONS


async def ask_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    rows, errors = parse_buttons(update.message.text or "")
    if errors:
        await update.message.reply_text("❌ Ошибки в кнопках:\n- " + "\n- ".join(errors))
        return ASK_BUTTONS

    context.user_data["buttons_rows"] = rows
    context.user_data["reply_markup"] = InlineKeyboardMarkup(rows) if rows else None
    await update.message.reply_text(
        "🧩 Шаг 5/5\n"
        "Отправь стикер (можно premium) 😎\n"
        "или `-`, чтобы пропустить."
    )
    return ASK_STICKER


async def preview_with_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["sticker_file_id"] = update.message.sticker.file_id
    return await send_preview(update, context)


async def preview_without_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if (update.message.text or "").strip() != "-":
        await update.message.reply_text("❌ Отправь стикер или `-`.")
        return ASK_STICKER
    context.user_data["sticker_file_id"] = None
    return await send_preview(update, context)


async def send_preview(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = context.user_data.get("reply_markup")
    text = context.user_data["post_text"]
    entities: List[MessageEntity] = context.user_data.get("post_entities", [])
    photo_file_id = context.user_data.get("photo_file_id")

    await update.message.reply_text(
        "👀 Предпросмотр ниже.\nЕсли всё ок: `yes`\nЕсли переделать: `no`"
    )
    if photo_file_id:
        await update.message.reply_photo(
            photo=photo_file_id,
            caption=text,
            caption_entities=entities,
            reply_markup=keyboard,
        )
    else:
        await update.message.reply_text(text, entities=entities, reply_markup=keyboard)
    if context.user_data.get("sticker_file_id"):
        await update.message.reply_sticker(context.user_data["sticker_file_id"])
    return CONFIRM


async def publish(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    answer = (update.message.text or "").strip().lower()
    if answer not in {"yes", "no"}:
        await update.message.reply_text("Ответь `yes` или `no`.")
        return CONFIRM
    if answer == "no":
        await update.message.reply_text("🔁 Ок, начнём заново. Введи chat_id.")
        return ASK_CHAT_ID

    chat_id = context.user_data["chat_id"]
    post_text = context.user_data["post_text"]
    entities: List[MessageEntity] = context.user_data.get("post_entities", [])
    rows = context.user_data.get("buttons_rows", [])
    keyboard = InlineKeyboardMarkup(rows) if rows else None
    photo_file_id = context.user_data.get("photo_file_id")
    sticker_file_id = context.user_data.get("sticker_file_id")

    try:
        if photo_file_id:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo_file_id,
                caption=post_text,
                caption_entities=entities,
                reply_markup=keyboard,
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=post_text,
                entities=entities,
                reply_markup=keyboard,
            )
        if sticker_file_id:
            await context.bot.send_sticker(chat_id=chat_id, sticker=sticker_file_id)
    except Exception as e:
        logger.exception("Send post failed")
        await update.message.reply_text(f"❌ Не получилось отправить пост: {e}")
        return ConversationHandler.END

    await update.message.reply_text("✅ Готово! Пост опубликован.")
    return ConversationHandler.END


async def redak(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только админ может менять цену.")
        return
    await update.message.reply_text("ℹ️ Цена фиксирована: 1 XTR навсегда.")


async def redakprem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только админ может менять цену.")
        return
    await update.message.reply_text("ℹ️ Цена фиксирована: 1 XTR навсегда.")


async def prem(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if not is_admin(user_id):
        await update.message.reply_text("❌ Только админ.")
        return
    if not context.args:
        await update.message.reply_text("Использование: /prem add 123456789 | /prem del 123456789 | /prem list")
        return
    action = context.args[0].lower()
    if action == "list":
        ids = state["premium_user_ids"]
        await update.message.reply_text("🌟 Premium users:\n" + ("\n".join(map(str, ids)) if ids else "empty"))
        return
    if len(context.args) < 2 or not context.args[1].isdigit():
        await update.message.reply_text("Нужен user_id: /prem add 123456789")
        return
    target = int(context.args[1])
    if action == "add":
        if target not in state["premium_user_ids"]:
            state["premium_user_ids"].append(target)
            save_state()
        await update.message.reply_text(f"✅ Добавлен в premium: {target}")
    elif action == "del":
        if target in state["premium_user_ids"]:
            state["premium_user_ids"].remove(target)
            save_state()
        await update.message.reply_text(f"✅ Удален из premium: {target}")
    else:
        await update.message.reply_text("Использование: /prem add|del|list ...")


async def admins(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = "👮 Админы:\n" + "\n".join(str(x) for x in ADMIN_IDS)
    await update.message.reply_text(text)


def main() -> None:
    token = BOT_TOKEN.strip()
    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError("Set BOT_TOKEN in file and run again.")
    load_state()

    app = Application.builder().token(token).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("newpost", new_post)],
        states={
            ASK_CHAT_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_text)],
            ASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_media)],
            ASK_MEDIA: [
                MessageHandler(filters.PHOTO & ~filters.COMMAND, ask_buttons_from_media),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ask_buttons_no_media),
            ],
            ASK_BUTTONS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_sticker)],
            ASK_STICKER: [
                MessageHandler(filters.Sticker.ALL & ~filters.COMMAND, preview_with_sticker),
                MessageHandler(filters.TEXT & ~filters.COMMAND, preview_without_sticker),
            ],
            CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, publish)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("pay", pay_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("redak", redak))
    app.add_handler(CommandHandler("redakprem", redakprem))
    app.add_handler(CommandHandler("prem", prem))
    app.add_handler(CommandHandler("admins", admins))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(conv)
    app.add_error_handler(error_handler)

    logger.info("Bot started")
    app.run_polling(close_loop=False)


if __name__ == "__main__":
    main()
