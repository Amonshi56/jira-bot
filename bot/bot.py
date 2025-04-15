from aiogram import Bot, Router, types, F
from aiogram.fsm.context import FSMContext
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.state import StatesGroup, State
from aiogram import Dispatcher
import task_storage
import re
import asyncio
import config
import aiohttp
import json
import certifi

bot = Bot(token=config.API_TOKEN)
router = Router()

# -----------------------------
# FSM STATES
# -----------------------------

class UnblockUser(StatesGroup):
    waiting_for_username = State()

class AuthState(StatesGroup):
    waiting_for_password = State()

class CreateIssue(StatesGroup):
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_photos = State() 
    waiting_for_severity = State()
    waiting_for_autor_info = State()

# -----------------------------
# MAPS
# -----------------------------
SEVERITY_MAPPING = {
    "Высокий": "High",
    "Средний": "Medium",
    "Низкий": "Low"
}

# -----------------------------
# UTILS
# -----------------------------
def escape_markdown(text: str) -> str:
    return re.sub(r'([\\`_{}\[\]()#+\-.!|<>^&=])', r'\\\1', text)

# -----------------------------
# JIRA INTEGRATION
# -----------------------------

async def create_jira_issue(summary, description, severity, user_id, project_key, issue_type="Task"):
    headers = {
        "Authorization": f"Bearer {config.JIRA_API_TOKEN}",
        "Content-Type": "application/json"
    }

    payload = {
        "fields": {
            "project": {"key": project_key},
            "summary": summary,
            "description": description,
            "issuetype": {"name": issue_type},
            'priority': {'name': severity},
            "labels": [f"user_id:{user_id}"] 
        }
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(config.JIRA_API_URL, headers=headers, json=payload) as response:
            if response.status == 201:
                data = await response.json()
                issue_key = data["key"]
                issue_url = f"{config.JIRA_BASE_URL}/browse/{issue_key}"
                print("Задача создана:", issue_url)
                return issue_url, issue_key
            else:
                text = await response.text()
                print("Ошибка при создании задачи:", response.status)
                print(text)
                return None

async def attach_photos_to_issue(issue_key: str, photo_urls: list[str]):
    headers = {
        "Authorization": f"Bearer {config.JIRA_API_TOKEN}",
        "X-Atlassian-Token": "no-check"
    }

    upload_url = f"{config.JIRA_BASE_URL}/rest/api/2/issue/{issue_key}/attachments"
    
    async with aiohttp.ClientSession() as session:
        for url in photo_urls:
            print(f"Попытка прикрепить фото с URL: {url}")
            await upload_photo(url, session, upload_url, headers)

async def upload_photo(url, session, upload_url, headers):
    try:
        async with session.get(url) as resp:
            if resp.status == 200:
                photo_data = await resp.read()
                filename = url.split("/")[-1]

                form = aiohttp.FormData()
                form.add_field("file", photo_data, filename=filename)

                async with session.post(upload_url, headers=headers, data=form) as attach_resp:
                    response_text = await attach_resp.text()
                    if attach_resp.status != 200:
                        print(f"Ошибка при добавлении {filename}: {attach_resp.status}")
                        print(f"Ответ от Jira: {response_text}")
                    else:
                        print(f"✅ Успешно прикреплён файл: {filename}")
                        print(f"Ответ от Jira: {response_text}")
            else:
                print(f"Не удалось скачать фото: {url}, статус: {resp.status}")
    except Exception as e:
        print(f"Ошибка при обработке фото {url}: {str(e)}")

# -----------------------------
# KEYBOARDS
# -----------------------------

def get_inline_start_keyboard(is_admin=False):
    buttons = [
        [
            InlineKeyboardButton(text="Создать задачу", callback_data="create_task"),
            InlineKeyboardButton(text="Создать ошибку", callback_data="create_bug")
        ],
        [
            InlineKeyboardButton(text="Мои задачи", callback_data="my_tasks")
        ]
    ]
    if is_admin:
        buttons.append(
            [InlineKeyboardButton(text="🔓 Разблокировать пользователя", callback_data="unblock_user")]
        )
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_continue_inline_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Продолжить", callback_data="continue_after_photos")]
        ]
    )

def get_inline_severity_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🔴 Высокий", callback_data="Высокий"),
                InlineKeyboardButton(text="🟠 Средний", callback_data="Средний"),
                InlineKeyboardButton(text="🟢 Низкий", callback_data="Низкий")
            ]
        ]
    ) 

# -----------------------------
# COMMAND HANDLERS
# -----------------------------        

@router.message(Command("start"))
async def start(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    if message.chat.id == config.BLOCKED_CHAT_ID:
        return

    if await task_storage.in_block(chat_id):
        await message.answer("🚫 У вас нет доступа к этому боту.")
        return

    if await task_storage.in_active(chat_id):
        await task_storage.add_user(message)
        is_admin = chat_id in config.ADMIN_ID
        if is_admin:
            await message.answer("Привет! Выберите действие:", reply_markup=get_inline_start_keyboard(is_admin=True))
            return
        await message.answer("Привет! Выберите действие:", reply_markup=get_inline_start_keyboard(is_admin=False))
        return

    await message.answer("🔐 Введите пароль для доступа:")
    await state.set_state(AuthState.waiting_for_password)


@router.message(AuthState.waiting_for_password)
async def process_password(message: types.Message, state: FSMContext):
    chat_id = message.chat.id
    username = message.chat.username
    password = message.text.strip()
    attempts = await task_storage.get_auth_attempts(chat_id)

    if attempts >= 5:
        await task_storage.block_user(chat_id, "Превышено число попыток авторизации", username)
        await state.clear()
        await message.answer("🚫 Вы ввели неправильный пароль 5 раз. Доступ заблокирован.")
        return
    if password == config.ACCESS_PASSWORD:
        await task_storage.add_user(message)
        await task_storage.clear_auth_attempts(chat_id)
        await state.clear()
        await message.answer("✅ Доступ разрешён. Добро пожаловать!")
        await start(message, state)
    else:
        await task_storage.increment_auth_attempts(chat_id, username)
        remaining = 5 - (attempts + 1)
        await message.answer(
            f"❌ Неверный пароль. Осталось попыток: {remaining}"
        )

# -----------------------------
# TASK HANDLERS
# -----------------------------

@router.callback_query(F.data.in_({"create_task", "create_bug"}))
async def handle_issue_type(callback: types.CallbackQuery, state: FSMContext):
    issue_type = "Task" if callback.data == "create_task" else "Ошибка"
    await state.update_data(issue_type=issue_type, photos=[])
    await state.set_state(CreateIssue.waiting_for_title)
    await callback.message.answer("Введите название:")
    await callback.answer()

@router.message(CreateIssue.waiting_for_title)
async def process_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await state.set_state(CreateIssue.waiting_for_description)
    await message.answer("Отправьте описание.")


@router.message(CreateIssue.waiting_for_description, F.content_type == types.ContentType.TEXT)
async def process_description(message: types.Message, state: FSMContext):
    description = message.text.strip()
    if not description:
        await message.answer("Описание не может быть пустым. Пожалуйста, введите описание задачи.")
        return

    await state.update_data(description=description)
    await state.set_state(CreateIssue.waiting_for_photos)
    await message.answer(
        "Описание сохранено. Если хотите, прикрепите фото. Когда закончите — нажмите \"Продолжить\".",
        reply_markup=get_continue_inline_keyboard()
    )

@router.message(CreateIssue.waiting_for_photos, F.content_type == types.ContentType.PHOTO)
async def process_photos(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    photos = user_data.get("photos", [])

    file_id = message.photo[-1].file_id
    file_info = await bot.get_file(file_id)
    file_url = f"https://api.telegram.org/file/bot{config.API_TOKEN}/{file_info.file_path}"

    photos.append(file_url)
    await state.update_data(photos=photos)
    await message.answer("Фото добавлено. Можете прикрепить ещё или нажмите 'Продолжить'.",
        reply_markup=get_continue_inline_keyboard()
    )


@router.callback_query(F.data == "continue_after_photos")
async def handle_continue_after_photos(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(CreateIssue.waiting_for_severity)
    await callback.message.answer("Теперь выберите уровень важности:", reply_markup=get_inline_severity_keyboard())
    await callback.answer()



@router.callback_query(F.data.in_({"Высокий", "Средний", "Низкий"}))
async def process_severity(callback: types.CallbackQuery, state: FSMContext):
    await state.update_data(severity=callback.data)
    await state.set_state(CreateIssue.waiting_for_autor_info)
    await callback.message.answer(
        "Введите ваше ФИО и номер телефона (например: Иванов Иван, +79991234567):")
    await callback.answer()

@router.message(CreateIssue.waiting_for_autor_info)
async def process_author_info(message: types.Message, state: FSMContext):
    user_data = await state.get_data()
    author_info = message.text.strip()
    await state.update_data(author_info=author_info)

    title = user_data["title"]
    description = user_data["description"]
    severity = user_data["severity"]
    issue_type = user_data["issue_type"]
    photos = user_data.get("photos", [])

    safe_title = escape_markdown(title)
    safe_description = escape_markdown(description)
    safe_severity = escape_markdown(severity)
    safe_author = escape_markdown(author_info)

    issue_url, issue_key = await create_jira_issue(
        summary=title,
        description=f"{description}\n\n*Автор:* {author_info}\n*Уровень важности:* {severity}",
        severity=SEVERITY_MAPPING.get(severity, "Medium"),
        user_id=message.from_user.id,
        project_key=config.JIRA_PROJECT_KEY,
        issue_type=issue_type
    )

    if issue_key:
        await attach_photos_to_issue(issue_key, photos)
        issue_url = f"{config.JIRA_BASE_URL}/browse/{issue_key}"
        await task_storage.save_task(message.from_user.id, issue_key, safe_title, "К выполнению")
        await message.answer(
            f"✅ { 'Задача' if issue_type == 'Task' else 'Ошибка' } создана\!\n\n"
            f"*Название:* {safe_title}\n"
            f"*Описание:* {safe_description}\n"
            f"*Автор:* {safe_author}\n"
            f"*Уровень важности:* {safe_severity}\n"
            f"{f'*Прикреплено фото: {len(photos)}*' if photos else ''}\n"
            f"Все созданные задачи можно посмотреть в разделе 'Мои задачи'",
            parse_mode="MarkdownV2"
        )
    else:
        await message.answer("Не удалось создать задачу.")
        return

    await state.clear()
    await start(message, state)

@router.callback_query(F.data == "my_tasks")
async def handle_my_tasks(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    tasks = await task_storage.get_tasks_for_user(user_id)
    if not tasks:
        await callback.message.answer("У вас пока нет задач 📭")
        reply_markup=get_inline_start_keyboard()
    else:
        text = ""
        for i, (task_key, summary, state, created_at) in enumerate(tasks, start=1):    
            text += (
                f"*{i}*. *{task_key}*\n"
                f"📌 _{summary}_\n"
                f"📅 {created_at} | 🏷️ *{state}*\n\n"
            )    
        await callback.message.answer(escape_markdown(text), parse_mode="MarkdownV2", reply_markup=get_inline_start_keyboard())
    await callback.answer()  

# -----------------------------
# UNBLOCK HANDLERS
# -----------------------------

@router.callback_query(F.data == "unblock_user")
async def handle_unblock_user(callback: types.CallbackQuery, state: FSMContext):
    if callback.from_user.id in config.ADMIN_ID:
        await callback.message.answer("Введите username пользователя без символа @ для разблокировки:", 
            parse_mode="Markdown")
        await callback.answer()
        await state.set_state(UnblockUser.waiting_for_username)
    else:
        await callback.answer("У вас нет прав на это действие.", show_alert=True)
        return

@router.message(UnblockUser.waiting_for_username)
async def process_unblock_username(message: types.Message, state: FSMContext):
    user_id = message.from_user.id

    if user_id not in config.ADMIN_ID:
        await start(message, state)

    username = message.text.strip()

    blocked_user = await task_storage.get_blocked_user_by_username(username)
    
    if not blocked_user:
        await message.answer(f"Пользователь с username `{username}` не найден в заблокированных.", parse_mode="Markdown")
        await start(message, state)
        return

    await task_storage.remove_from_blocked(username)
    await task_storage.clear_auth_attempts_username(username)
    await message.answer(f"Пользователь @{username} успешно разблокирован!")
    await start(message, state)


# -----------------------------
# MAIN ENTRY
# -----------------------------

async def main():
    await task_storage.init_db()
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

