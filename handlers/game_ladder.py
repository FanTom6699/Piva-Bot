# handlers/game_ladder.py
# ... (все импорты) ...
from settings import settings_manager # <-- ИМПОРТ МЕНЕДЖЕРА

# ... (прочий код лесенки) ...

@ladder_router.message(Command("ladder"))
async def cmd_ladder(message: Message, bot: Bot):
    chat_id = message.chat.id
    if chat_id in active_ladder_games:
        return await message.reply("Пожалуйста, подождите...")
    
    args = message.text.split()
    if len(args) != 2 or not args[1].isdigit():
        return await message.reply("Неверный формат...")
    
    stake = int(args[1])
    
    # --- ИЗМЕНЕНИЕ ЗДЕСЬ ---
    min_bet = settings_manager.ladder_min_bet
    max_bet = settings_manager.ladder_max_bet
    if not (min_bet <= stake <= max_bet):
        return await message.reply(f"Ставка должна быть от {min_bet} до {max_bet} 🍺.")
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---

    if not await check_user_registered(message, bot):
        return
    
    balance = await db.get_user_beer_rating(message.from_user.id)
    if balance < stake:
        return await message.reply(f"У вас недостаточно пива...")
        
    await start_ladder_game(message.chat, message.from_user, bot, stake)

# ... (остальной код лесенки) ...
