import json
import os
import random
import time
import telebot
from telebot import types

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
bot = telebot.TeleBot(TOKEN)

REPLIES_FILE = "replies.json"
ADMINS_FILE = "admins.json"

LOCATIONS = [
    {"name": "الأهرامات وأبو الهول", "type": "أثري"},
    {"name": "معبد الكرنك بالأقصر", "type": "أثري"},
    {"name": "قلعة صلاح الدين الأيوبي", "type": "أثري"},
    {"name": "المتحف المصري الكبير", "type": "أثري"},
    {"name": "مقابر وادي الملوك", "type": "أثري"},
    {"name": "مقهى بلدي على القهوة", "type": "عادي"},
    {"name": "مول تجاري كبير", "type": "عادي"},
    {"name": "مستشفى عام", "type": "عادي"},
    {"name": "محطة مترو الأنفاق", "type": "عادي"},
    {"name": "ملعب كرة قدم", "type": "عادي"},
    {"name": "مطار دولي", "type": "عادي"},
    {"name": "سوق شعبي", "type": "عادي"},
]


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[ERROR] saving {path}: {e}")


# { "chat_id": { "trigger": [ { "text": "...", "media_type": "photo|video|none", "media_id": "..." } ] } }
auto_replies = load_json(REPLIES_FILE, {})
# { "chat_id": [ { "id": 123, "name": "...", "username": "..." } ] }
group_admins = load_json(ADMINS_FILE, {})

adding_reply_state = {}      # user_id -> dict
deleting_reply_state = set() # user_id set
active_games = {}           # chat_id -> game_dict


def format_user_name(user):
    if not user:
        return "مستخدم"
    name = (user.first_name or "") + (f" {user.last_name}" if user.last_name else "")
    return name.strip() or f"User_{user.id}"


def is_chat_admin(chat_id, user_id):
    try:
        member = bot.get_chat_member(chat_id, user_id)
        return member.status in ["administrator", "creator"]
    except Exception:
        return False


def register_group_admin(chat_id, user):
    if not user or user.is_bot or chat_id > 0:
        return
    cid = str(chat_id)
    if cid not in group_admins:
        group_admins[cid] = []

    display_name = format_user_name(user)
    for adm in group_admins[cid]:
        if adm["id"] == user.id:
            adm["name"] = display_name
            adm["username"] = user.username or ""
            save_json(ADMINS_FILE, group_admins)
            return

    group_admins[cid].append({
        "id": user.id,
        "name": display_name,
        "username": user.username or "",
    })
    save_json(ADMINS_FILE, group_admins)


def sync_chat_admins(chat_id):
    cid = str(chat_id)
    if cid not in group_admins:
        group_admins[cid] = []
    try:
        tg_admins = bot.get_chat_administrators(chat_id)
        existing_by_id = {a["id"]: a for a in group_admins[cid]}
        for adm in tg_admins:
            u = adm.user
            if not u.is_bot:
                name = format_user_name(u)
                if u.id in existing_by_id:
                    existing_by_id[u.id]["name"] = name
                    existing_by_id[u.id]["username"] = u.username or ""
                else:
                    group_admins[cid].append({
                        "id": u.id,
                        "name": name,
                        "username": u.username or "",
                    })
        save_json(ADMINS_FILE, group_admins)
    except Exception:
        pass


def clear_user_states(user_id):
    adding_reply_state.pop(user_id, None)
    deleting_reply_state.discard(user_id)


# ================= /start & قائمة الأوامر =================
@bot.message_handler(commands=["start", "help"])
@bot.message_handler(func=lambda m: m.text and m.text.strip() in ["الاوامر", "الأوامر", "المساعدة"])
def send_help_menu(message):
    if message.chat.type != "private":
        register_group_admin(message.chat.id, message.from_user)

    text = (
        "⚡ **أهلاً بك في بوت Pro Max** ⚡\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🛡️ **أوامر الأدمنز (الردود التلقائية):**\n"
        "• `اضافة رد` — إضافة كلمة + بايو + صورة أو فيديو\n"
        "• `عرض الردود` — عرض الكلمات وحذفها بزراير فورية\n"
        "• `حذف رد` أو `حذف رد <الكلمة>` — حذف رد محدد\n\n"
        "🕵️‍♂️ **لعبة الجسوس (أقل عدد 3 لاعبين):**\n"
        "• `الجسوس` — فتح غرفة لعب والتصويت لكشف الجاسوس\n"
        "• `انهاء الجسوس` — إنهاء جولة عالقة في الجروب\n\n"
        "🚨 **نداء المشرفين:**\n"
        "• `نداء مشرف` — اختيار مشرف ومنشنته بشكل رايق\n\n"
        "💡 *ملاحظة:* في لعبة الجسوس لازم اللاعبين يدخلوا يكلموا البوت في الخاص الأول عشان يوصله المكان أو دور الجاسوس."
    )
    bot.reply_to(message, text, parse_mode="Markdown")


# ================= 1. إدارة الردود التلقائية (للأدمنز فقط) =================
@bot.message_handler(func=lambda m: m.text and m.text.strip() == "اضافة رد")
def start_add_reply(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚠️ الأمر ده مخصص للجروبات بس.")
        return

    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "🚫 معلش يا صاحبي، إضافة الردود التلقائية متاحة **للأدمنز فقط**.", parse_mode="Markdown")
        return

    register_group_admin(message.chat.id, message.from_user)
    clear_user_states(message.from_user.id)

    adding_reply_state[message.from_user.id] = {
        "step": "trigger",
        "chat_id": message.chat.id,
        "trigger": None,
        "text": None,
        "media_type": "none",
        "media_id": None,
    }
    bot.reply_to(
        message,
        "🔥 **تمام يا أدمن، هنبدأ نجهز الرد!**\n\n"
        "ابعت دلوقتي **الكلمة** اللي البوت هيرد عليها:\n"
        "*(أو ابعت `/الغاء` للإلغاء)*",
        parse_mode="Markdown"
    )


@bot.message_handler(
    func=lambda m: m.from_user and m.from_user.id in adding_reply_state,
    content_types=["text", "photo", "video"]
)
def process_add_reply_steps(message):
    uid = message.from_user.id
    state = adding_reply_state[uid]

    if message.text and message.text.strip() == "/الغاء":
        del adding_reply_state[uid]
        bot.reply_to(message, "❎ تم إلغاء إضافة الرد.")
        return

    step = state["step"]

    if step == "trigger":
        if not message.text or not message.text.strip():
            bot.reply_to(message, "ابعت كلمة نصية واضحة للرد عليها.")
            return
        state["trigger"] = message.text.strip().lower()
        state["step"] = "bio_text"
        bot.reply_to(
            message,
            "✍️ **حلو أوي!**\n"
            "ابعت دلوقتي **كلام البايو / الرد** اللي هيطلع مع الكلمة\n"
            "*(أو اكتب `بدون` لو عايز صورة أو فيديو بس)*:",
            parse_mode="Markdown"
        )

    elif step == "bio_text":
        if not message.text:
            bot.reply_to(message, "ابعت كلام البايو كنص الأول، أو اكتب `بدون`.")
            return
        txt = message.text.strip()
        state["text"] = "" if txt == "بدون" else txt
        state["step"] = "media"
        bot.reply_to(
            message,
            "🎬 **تمام يا وحش!**\n"
            "عايز ترفعلو **صورة** أو **فيديو**؟ ابعته دلوقتي، أو اكتب `تخطي` لو مش عايز ميديا.",
            parse_mode="Markdown"
        )

    elif step == "media":
        if message.content_type == "photo":
            state["media_type"] = "photo"
            state["media_id"] = message.photo[-1].file_id
        elif message.content_type == "video":
            state["media_type"] = "video"
            state["media_id"] = message.video.file_id
        elif message.text and message.text.strip() == "تخطي":
            state["media_type"] = "none"
            state["media_id"] = None
        else:
            bot.reply_to(message, "ابعت **صورة** أو **فيديو**، أو اكتب `تخطي`.", parse_mode="Markdown")
            return

        if not state["text"] and state["media_type"] == "none":
            bot.reply_to(message, "⚠️ مينفعش الرد يكون فاضي من الكلام والميديا معاً! ابعت نص أو صورة أو فيديو.")
            return

        cid = str(state["chat_id"])
        if cid not in auto_replies:
            auto_replies[cid] = {}

        trig = state["trigger"]
        if trig not in auto_replies[cid]:
            auto_replies[cid][trig] = []
        elif isinstance(auto_replies[cid][trig], dict):
            auto_replies[cid][trig] = [auto_replies[cid][trig]]

        auto_replies[cid][trig].append({
            "text": state["text"],
            "media_type": state["media_type"],
            "media_id": state["media_id"],
        })
        save_json(REPLIES_FILE, auto_replies)
        del adding_reply_state[uid]

        count_for_word = len(auto_replies[cid][trig])
        bot.reply_to(
            message,
            f"✅ **تم حفظ الرد التلقائي بنجاح!**\n"
            f"• الكلمة: `{trig}`\n"
            f"• عدد الردود المسجلة لهذه الكلمة: `{count_for_word}`",
            parse_mode="Markdown"
        )


def _get_word_entries(cid, word):
    raw = auto_replies.get(cid, {}).get(word)
    if not raw:
        return []
    return raw if isinstance(raw, list) else [raw]


def _build_replies_summary(cid):
    chat_replies = auto_replies.get(cid, {})
    lines = ["📋 **قائمة الردود التلقائية في الجروب:**\n"]
    for idx, word in enumerate(chat_replies.keys(), start=1):
        entries = _get_word_entries(cid, word)
        types_desc = []
        for e in entries:
            mt = e.get("media_type", "none")
            lbl = "🖼 صورة" if mt == "photo" else ("🎬 فيديو" if mt == "video" else "📝 نص")
            if e.get("text"):
                lbl += "+بايو"
            types_desc.append(lbl)
        lines.append(f"{idx}. `{word}` — ({' | '.join(types_desc)})")
    return "\n".join(lines)


def _build_replies_markup(chat_id, cid):
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for word in auto_replies.get(cid, {}).keys():
        cb = f"delrep:{chat_id}:{word}"
        if len(cb.encode("utf-8")) <= 64:
            buttons.append(types.InlineKeyboardButton(text=f"🗑 {word[:22]}", callback_data=cb))
    if buttons:
        markup.add(*buttons)
    return markup


@bot.message_handler(func=lambda m: m.text and m.text.strip() == "عرض الردود")
def list_auto_replies(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚠️ الأمر ده مخصص للجروبات بس.")
        return

    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "🚫 معلش، عرض الردود التلقائية متاح **للأدمنز فقط**.", parse_mode="Markdown")
        return

    register_group_admin(message.chat.id, message.from_user)
    cid = str(message.chat.id)
    if not auto_replies.get(cid):
        bot.reply_to(message, "📭 مفيش أي ردود تلقائية متسجلة في الجروب ده حالياً.")
        return

    msg_text = _build_replies_summary(cid) + "\n\nاضغط على زر أي كلمة تحت لحذفها فوراً 👇"
    bot.reply_to(message, msg_text, parse_mode="Markdown", reply_markup=_build_replies_markup(message.chat.id, cid))


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("delrep:"))
def handle_delete_reply_callback(call):
    parts = call.data.split(":", 2)
    if len(parts) != 3:
        return
    chat_id = int(parts[1])
    trigger_word = parts[2]

    if not is_chat_admin(chat_id, call.from_user.id):
        bot.answer_callback_query(call.id, "🚫 الحذف متاح للأدمنز فقط.", show_alert=True)
        return

    cid = str(chat_id)
    if cid in auto_replies and trigger_word in auto_replies[cid]:
        del auto_replies[cid][trigger_word]
        if not auto_replies[cid]:
            del auto_replies[cid]
        save_json(REPLIES_FILE, auto_replies)
        bot.answer_callback_query(call.id, f"🗑 تم حذف: {trigger_word}")

        if not auto_replies.get(cid):
            try:
                bot.edit_message_text(
                    "✅ تم حذف آخر رد، ومفيش ردود تلقائية متبقية في الجروب.",
                    chat_id=chat_id,
                    message_id=call.message.message_id
                )
            except Exception:
                pass
        else:
            try:
                bot.edit_message_text(
                    _build_replies_summary(cid) + "\n\nاضغط على زر أي كلمة تحت لحذفها فوراً 👇",
                    chat_id=chat_id,
                    message_id=call.message.message_id,
                    parse_mode="Markdown",
                    reply_markup=_build_replies_markup(chat_id, cid)
                )
            except Exception:
                pass
    else:
        bot.answer_callback_query(call.id, "الرد ده مش موجود بالفعل.", show_alert=True)


@bot.message_handler(func=lambda m: m.text and (m.text.strip() == "حذف رد" or m.text.strip().startswith("حذف رد ")))
def delete_auto_reply_command(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚠️ الأمر ده مخصص للجروبات بس.")
        return

    if not is_chat_admin(message.chat.id, message.from_user.id):
        bot.reply_to(message, "🚫 معلش، حذف الردود التلقائية متاح **للأدمنز فقط**.", parse_mode="Markdown")
        return

    register_group_admin(message.chat.id, message.from_user)
    raw = message.text.strip()

    if raw == "حذف رد":
        clear_user_states(message.from_user.id)
        deleting_reply_state.add(message.from_user.id)
        bot.reply_to(message, "🗑 ابعت دلوقتي **الكلمة** اللي عايز تحذف ردها (أو ابعت `/الغاء`):", parse_mode="Markdown")
        return

    target_word = raw.replace("حذف رد ", "", 1).strip().lower()
    cid = str(message.chat.id)
    if cid in auto_replies and target_word in auto_replies[cid]:
        del auto_replies[cid][target_word]
        if not auto_replies[cid]:
            del auto_replies[cid]
        save_json(REPLIES_FILE, auto_replies)
        bot.reply_to(message, f"🗑 تم حذف الرد الخاص بكلمة `{target_word}` بنجاح.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"⚠️ مفيش رد متسجل بالكلمة `{target_word}`.", parse_mode="Markdown")


@bot.message_handler(
    func=lambda m: m.from_user and m.from_user.id in deleting_reply_state,
    content_types=["text"]
)
def process_delete_reply_word(message):
    uid = message.from_user.id
    deleting_reply_state.discard(uid)

    if message.text.strip() == "/الغاء":
        bot.reply_to(message, "❎ تم إلغاء الحذف.")
        return

    target_word = message.text.strip().lower()
    cid = str(message.chat.id)
    if cid in auto_replies and target_word in auto_replies[cid]:
        del auto_replies[cid][target_word]
        if not auto_replies[cid]:
            del auto_replies[cid]
        save_json(REPLIES_FILE, auto_replies)
        bot.reply_to(message, f"🗑 تم حذف الرد الخاص بكلمة `{target_word}` بنجاح.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"⚠️ مفيش رد متسجل بالكلمة `{target_word}`.", parse_mode="Markdown")


# ================= 2. نداء مشرف =================
@bot.message_handler(func=lambda m: m.text and m.text.strip() == "نداء مشرف")
def call_moderator_menu(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚠️ الأمر ده شغال جوه الجروبات بس.")
        return

    register_group_admin(message.chat.id, message.from_user)
    sync_chat_admins(message.chat.id)

    cid = str(message.chat.id)
    admins_list = group_admins.get(cid, [])
    if not admins_list:
        bot.reply_to(message, "مفيش مشرفين مسجلين حالياً، خلي أي مشرف يبعت رسالة أو يعمل `اضافة رد` الأول.")
        return

    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for adm in admins_list:
        cb = f"modcall:{message.from_user.id}:{adm['id']}"
        buttons.append(types.InlineKeyboardButton(text=f"👮‍♂️ {adm['name'][:26]}", callback_data=cb[:64]))

    markup.add(*buttons)
    bot.reply_to(message, "🚨 **اختار المشرف اللي عايز تنديله 👇**", parse_mode="Markdown", reply_markup=markup)


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("modcall:"))
def handle_mod_call_click(call):
    parts = call.data.split(":")
    if len(parts) != 3:
        return
    target_id = int(parts[2])
    cid = str(call.message.chat.id)

    target_adm = None
    for adm in group_admins.get(cid, []):
        if adm["id"] == target_id:
            target_adm = adm
            break

    if not target_adm:
        bot.answer_callback_query(call.id, "المشرف ده مش موجود في القائمة.", show_alert=True)
        return

    mention = (
        f"@{target_adm['username']}"
        if target_adm.get("username")
        else f"[{target_adm['name']}](tg://user?id={target_adm['id']})"
    )

    lines = [
        f"{mention} — **كلم يعم عشان ده شكله هيصدعنا** 😂🔥",
        f"{mention} — **الحق يا معلم، فيه نداء جاد وشكلو هيصدعنا** 😅🚨",
        f"{mention} — **تعالى شوف الحوار ده، كلم يعم عشان شكله هيصدعنا** 👀⚡",
    ]
    chosen = random.choice(lines)

    bot.answer_callback_query(call.id, "تم إرسال النداء ✅")
    bot.send_message(call.message.chat.id, chosen, parse_mode="Markdown")


# ================= 3. لعبة الجسوس (أقل عدد 3 لاعبين) =================
def build_lobby_markup(chat_id):
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🙋‍♂️ انضم للعبة", callback_data=f"spy_join:{chat_id}"))
    markup.add(types.InlineKeyboardButton("🚀 ابدأ اللعبة (3 لاعبين فأكثر)", callback_data=f"spy_start:{chat_id}"))
    return markup


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ["انهاء الجسوس", "إنهاء الجسوس"])
def cancel_spy_game(message):
    chat_id = message.chat.id
    if chat_id not in active_games:
        bot.reply_to(message, "مفيش لعبة جسوس شغالة حالياً.")
        return
    game = active_games[chat_id]
    if message.from_user.id != game["creator_id"] and not is_chat_admin(chat_id, message.from_user.id):
        bot.reply_to(message, "إنهاء اللعبة متاح لمنشئ اللعبة أو الأدمنز فقط.")
        return
    del active_games[chat_id]
    bot.reply_to(message, "🛑 تم إنهاء لعبة الجسوس.")


@bot.message_handler(func=lambda m: m.text and m.text.strip() in ["الجسوس", "لعبة الجسوس"])
def create_spy_game(message):
    if message.chat.type == "private":
        bot.reply_to(message, "⚠️ لعبة الجسوس بتتلعب جوه الجروب.")
        return

    chat_id = message.chat.id
    if chat_id in active_games and active_games[chat_id]["phase"] in ["lobby", "playing"]:
        bot.reply_to(message, "⚠️ فيه لعبة جسوس شغالة أو مستنية لاعبين حالياً في الجروب! (اكتب `انهاء الجسوس` لإلغائها).", parse_mode="Markdown")
        return

    creator = message.from_user
    creator_name = format_user_name(creator)

    active_games[chat_id] = {
        "phase": "lobby",
        "creator_id": creator.id,
        "players": {creator.id: creator_name},
        "spy_id": None,
        "location": None,
        "votes": {},
        "started_at": time.time(),
    }

    text = (
        "🕵️‍♂️ **بدأت غرفة لعبة الجسوس!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• أقل عدد لاعبين: **3 لاعبين**\n"
        "• الفكرة: الكل هيعرف المكان (هل هو **أثري** ولا **عادي**) في الخاص ما عدا **الجاسوس**!\n"
        "• اسألوا بعض هل المكان ده أثري ولا عادي وحاولوا تكشفوا الجاسوس.\n\n"
        f"👥 اللاعبون المنضمون (1):\n1. {creator_name}"
    )
    bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=build_lobby_markup(chat_id))


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("spy_join:"))
def spy_join_callback(call):
    chat_id = int(call.data.split(":")[1])
    game = active_games.get(chat_id)
    if not game or game["phase"] != "lobby":
        bot.answer_callback_query(call.id, "مفيش غرفة انضمام مفتوحة دلوقتي.", show_alert=True)
        return

    user = call.from_user
    if user.is_bot:
        return

    name = format_user_name(user)
    if user.id in game["players"]:
        bot.answer_callback_query(call.id, "أنت منضم بالفعل 👍")
        return

    game["players"][user.id] = name
    bot.answer_callback_query(call.id, "تم انضمامك للعبة ✅")

    players_list = "\n".join([f"{i+1}. {p}" for i, p in enumerate(game["players"].values())])
    text = (
        "🕵️‍♂️ **غرفة لعبة الجسوس!**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "• أقل عدد لاعبين: **3 لاعبين**\n\n"
        f"👥 اللاعبون المنضمون ({len(game['players'])}):\n{players_list}"
    )
    try:
        bot.edit_message_text(
            text,
            chat_id=chat_id,
            message_id=call.message.message_id,
            parse_mode="Markdown",
            reply_markup=build_lobby_markup(chat_id)
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("spy_start:"))
def spy_start_callback(call):
    chat_id = int(call.data.split(":")[1])
    game = active_games.get(chat_id)
    if not game or game["phase"] != "lobby":
        bot.answer_callback_query(call.id, "اللعبة مش في مرحلة الانتظار.", show_alert=True)
        return

    player_ids = list(game["players"].keys())
    if len(player_ids) < 3:
        bot.answer_callback_query(
            call.id,
            f"⚠️ اللعبة متشتغلش غير بـ 3 لاعبين على الأقل! (الحالي: {len(player_ids)})",
            show_alert=True
        )
        return

    spy_id = random.choice(player_ids)
    location = random.choice(LOCATIONS)

    game["phase"] = "playing"
    game["spy_id"] = spy_id
    game["location"] = location
    game["votes"] = {}

    failed_dm = []
    for pid, pname in game["players"].items():
        try:
            if pid == spy_id:
                bot.send_message(
                    pid,
                    "🕵️‍♂️ **أنت الجاسوس!**\n"
                    "مش هتعرف اسم المكان ولا نوعه. ركز في أسئلة الناس لبعض (هل المكان أثري ولا عادي؟) وحاول تبان إنك فاهم من غير ما تتكشف!"
                )
            else:
                bot.send_message(
                    pid,
                    f"📍 **المكان هو:** {location['name']}\n"
                    f"🏛️ **نوع المكان:** {location['type']}\n\n"
                    "اسألوا بعض في الجروب: المكان ده أثري ولا عادي؟ وراقبوا مين اللي مش عارف التفاصيل!"
                )
        except Exception:
            failed_dm.append(pname)

    if failed_dm:
        game["phase"] = "lobby"
        names_str = "، ".join(failed_dm)
        bot.answer_callback_query(call.id, "بعض اللاعبين لم يفتحوا الخاص للبوت!", show_alert=True)
        bot.send_message(
            chat_id,
            f"⚠️ مقدرتش أبعت رسالة خاصة لـ: {names_str}\n"
            f"لازم يدخلوا يكلموا البوت في الخاص الأول ويضغطوا Start، وبعدين اضغطوا **ابدأ اللعبة** تاني."
        )
        return

    bot.answer_callback_query(call.id, "تم إرسال الأدوار في الخاص ✅")

    vote_markup = types.InlineKeyboardMarkup(row_width=2)
    vote_btns = [
        types.InlineKeyboardButton(
            text=f"🎯 {pname[:24]}",
            callback_data=f"spy_vote:{chat_id}:{pid}"
        )
        for pid, pname in game["players"].items()
    ]
    vote_markup.add(*vote_btns)

    bot.send_message(
        chat_id,
        "🔥 **اللعبة بدأت!**\n"
        "تم إرسال المكان في الخاص للجميع ما عدا الجاسوس.\n"
        "ابدأوا اسألوا بعض: **المكان ده أثري ولا عادي؟**\n\n"
        "ولما تحددوا مين الجاسوس، اختاروا اسمه من الزراير تحت 👇",
        reply_markup=vote_markup
    )


@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("spy_vote:"))
def spy_vote_callback(call):
    _, chat_id_str, accused_id_str = call.data.split(":")
    chat_id = int(chat_id_str)
    accused_id = int(accused_id_str)
    voter_id = call.from_user.id

    game = active_games.get(chat_id)
    if not game or game["phase"] != "playing":
        bot.answer_callback_query(call.id, "الجولة دي خلصت أو مش شغالة.", show_alert=True)
        return

    if voter_id not in game["players"]:
        bot.answer_callback_query(call.id, "أنت مش مشارك في الجولة دي.", show_alert=True)
        return

    game["votes"][voter_id] = accused_id
    accused_name = game["players"].get(accused_id, "لاعب")
    bot.answer_callback_query(call.id, f"تم تسجيل صوتك ضد {accused_name} ✅")

    if len(game["votes"]) == len(game["players"]):
        finish_spy_game(chat_id)


def finish_spy_game(chat_id):
    game = active_games.get(chat_id)
    if not game:
        return

    game["phase"] = "finished"
    spy_id = game["spy_id"]
    spy_name = game["players"].get(spy_id, "الجاسوس")
    loc = game["location"]

    tally = {}
    for target in game["votes"].values():
        tally[target] = tally.get(target, 0) + 1

    most_voted_id = max(tally.items(), key=lambda x: x[1])[0] if tally else None
    most_voted_name = game["players"].get(most_voted_id, "لا أحد")

    votes_lines = []
    for vid, tid in game["votes"].items():
        v_name = game["players"].get(vid, "لاعب")
        t_name = game["players"].get(tid, "لاعب")
        votes_lines.append(f"• {v_name} ⬅️ {t_name}")

    caught = (most_voted_id == spy_id)
    verdict = (
        "🎉 **تم كشف الجاسوس! فريق اللاعبين كسب!**"
        if caught
        else "😈 **الجاسوس هرب ومحدش عرف يكشفه! الجاسوس كسب!**"
    )

    result_text = (
        f"📊 **نتيجة الجولة:**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{verdict}\n\n"
        f"🕵️‍♂️ الجاسوس كان: **{spy_name}**\n"
        f"📍 المكان كان: **{loc['name']}** ({loc['type']})\n"
        f"🗳️ الأكثر تصويتاً: **{most_voted_name}**\n\n"
        f"📝 تفاصيل الأصوات:\n" + ("\n".join(votes_lines) if votes_lines else "مفيش أصوات")
    )
    bot.send_message(chat_id, result_text, parse_mode="Markdown")
    del active_games[chat_id]


# ================= 4. الرد التلقائي على الكلمات =================
@bot.message_handler(func=lambda m: True, content_types=["text"])
def handle_auto_replies(message):
    if message.from_user and not message.from_user.is_bot:
        register_group_admin(message.chat.id, message.from_user)

    if not message.text:
        return

    cid = str(message.chat.id)
    chat_replies = auto_replies.get(cid, {})
    txt = message.text.strip().lower()

    if txt in chat_replies:
        entries = _get_word_entries(cid, txt)
        if not entries:
            return
        item = random.choice(entries)
        media_type = item.get("media_type", "none")
        media_id = item.get("media_id")
        caption = item.get("text") or None

        try:
            if media_type == "photo" and media_id:
                bot.send_photo(message.chat.id, media_id, caption=caption, reply_to_message_id=message.message_id)
            elif media_type == "video" and media_id:
                bot.send_video(message.chat.id, media_id, caption=caption, reply_to_message_id=message.message_id)
            else:
                if caption:
                    bot.reply_to(message, caption)
        except Exception as e:
            print(f"[ERROR] sending auto reply: {e}")


if __name__ == "__main__":
    print("Pro Max Bot is running...")
    bot.infinity_polling(skip_pending=True)
