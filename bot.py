import os
import sys
import time
import asyncio  # FIXED: Handles non-blocking asynchronous delays
import io
import requests
import urllib.parse  # FIXED: Added to safely convert Turkish/Special characters in image prompts

import nextcord
from nextcord.ext import commands
import openai
import yaml
from logging42 import logger

from flask import Flask
import threading

app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# Sahte web sunucusunu botla aynı anda arka planda başlatır
threading.Thread(target=run_flask).start()


# GÜNCEL KUTUPHANE STANDARDI: OpenAI istemcisini yeni nesil yöntemle başlatır
client_ai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

intents = nextcord.Intents.default()
intents.guild_messages = True
intents.message_content = True

client = nextcord.Client(intents=intents)

# --- AKILLI VE EKONOMİK HAFIZA SİSTEMİ ALTYAPISI ---
USER_MEMORY = {}
MAX_MEMORY_LIMIT = 10  # Hafızada tutulacak maksimum mesaj sınırı (Prompt Caching ile %90 indirimli)

# Define a function to save the channel ID to the storage.yml file
def save_channel_id(guild_id, channel_id):
    storage = {'guilds': {}}
    if os.path.exists('storage.yml'):
        with open('storage.yml', 'r') as f:
            storage = yaml.safe_load(f)
    storage['guilds'][str(guild_id)] = {'channel_id': str(channel_id)}
    with open('storage.yml', 'w') as f:
        yaml.dump(storage, f)


# Define a function to fetch the channel ID from the storage.yml file
def get_channel_id(guild_id):
    if os.path.exists('storage.yml'):
        with open('storage.yml', 'r') as f:
            storage = yaml.safe_load(f)
            return storage['guilds'].get(str(guild_id), {}).get('channel_id')

@client.event
async def on_ready():
    logger.info(f'{client.user} has connected to Discord!')

@client.event
async def on_message(message):
    global USER_MEMORY
    
    # 1. IMMEDIATE FILTER: Completely ignore any message sent by a bot account
    if message.author.bot:
        return

    # 2. CHANNEL FILTER: Verify the exact channel configuration matches storage.yml
    target_channel_id = get_channel_id(message.guild.id)
    if not target_channel_id or str(message.channel.id) != str(target_channel_id):
        return

    # 3. TEXT FILTER: Ignore common command prefixes
    if message.content.startswith(('#', '.', '<')):
        return

    # Activate typing bubble inside the target channel
    async with message.channel.typing():
        start_time = int(time.time() * 1000)
        prompt = message.clean_content
        user_id = message.author.id
        logger.info(f'Got prompt from User {user_id}: "{prompt}"')

        response_text = ""
        image_file = None

        try:
            # Tetikleyici kelimeler esnetilerek Türkçe karakter hataları engellendi
            image_keywords = ["draw", "paint", "image", "picture", "resim", "ciz", "çiz", "görsel", "gorsel"]
            is_image_request = any(keyword in prompt.lower() for keyword in image_keywords)

            if is_image_request:
                logger.info("Executing Pollinations AI free image pipeline...")
                
                # KESİN DÜZELTME: Hizalama hatasına neden olan tüm boşluklar 4-8-12 kuralına göre sıfırlandı
                clean_prompt_text = prompt.replace(f"@{client.user.name}", "").strip()
                encoded_prompt = urllib.parse.quote(clean_prompt_text)
                
                # Pollinations ana sunucu adresi en güvenli formatta sabitlendi
                image_url = f"https://pollinations.ai{encoded_prompt}?width=1024&height=1024&model=flux&render=true"
                
                # Resmi harcama yapmadan (0 TL) hafızaya indiriyoruz
                img_response = requests.get(image_url, timeout=15)
                if img_response.status_code == 200:
                    image_file = nextcord.File(io.BytesIO(img_response.content), filename="generated_image.png")
                    response_text = f"🎨 Here is your **100% free** generated image for: *\"{prompt}\"*:"
                else:
                    response_text = "⚠️ Ücretsiz resim motoru şu an yoğun, lütfen az sonra tekrar deneyin."
            
            else:
                # ─── HAFIZALI STANDART METİN TAMAMLAMA SİSTEMİ ───
                if user_id not in USER_MEMORY:
                    USER_MEMORY[user_id] = []

                USER_MEMORY[user_id].append({"role": "user", "content": prompt})

                messages_payload = [
                    { 
                        "role": "system", 
                        "content": "You are a helpful and intelligent Discord AI assistant powered by GPT-5.4-Mini. You remember the ongoing conversation history with the user. Answer questions clearly, accurately, and natively in the user's language." 
                    }
                ]
                
                messages_payload.extend(USER_MEMORY[user_id])

                response = client_ai.chat.completions.create(
                    model='gpt-5.4-mini',
                    max_completion_tokens=1900,
                    n=1,
                    stop=None,
                    temperature=0.7,
                    messages=messages_payload
                )
                response_text = response.choices[0].message.content
                
                USER_MEMORY[user_id].append({"role": "assistant", "content": response_text})

                if len(USER_MEMORY[user_id]) > MAX_MEMORY_LIMIT:
                    USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_LIMIT:]
                
                logger.info(f"📊 [OpenAI Usage Tracker] -> {response.usage}")

        except Exception as e:
            logger.error(f"Sistem Hatasi: {e}")
            response_text = f"**⚠️ Bir hata oluştu! Detay: {e}**"

        # Resolve invite placeholders
        invite_link = "https://discord.com"
        if os.path.exists('config.yml'):
            try:
                with open('config.yml', 'r') as f:
                    local_config = yaml.safe_load(f)
                    if local_config and 'BOT_INVITE_LINK' in local_config:
                        invite_link = local_config['BOT_INVITE_LINK']
            except Exception:
                pass

        response_text = response_text.replace('#INVITE#', invite_link)
        
        # 4. CHUNKED DELIVERY USING ASYNC SLEEP (Prevents Discord API timeout retries)
        if not response_text.startswith('#NORESPOND'):
            if image_file:
                await message.reply(content=response_text, file=image_file)
            elif len(response_text) > 2000:
                chunks = [response_text[i:i+1900] for i in range(0, len(response_text), 1900)]
                for chunk in chunks:
                    await message.reply(chunk)
                    await asyncio.sleep(0.5)  
            else:
                await message.reply(response_text)

        end_time = int(time.time() * 1000)
        logger.success(f'Responded to a prompt in {end_time - start_time}ms!')

# Slash komut fonksiyonu eksiksiz olarak korundu
@client.slash_command(name='set_channel', description='Set the channel where the client listens for messages')
async def set_channel(ctx, channel: nextcord.TextChannel):
    await ctx.response.defer(ephemeral=True)
    
    if ctx.user.guild_permissions.administrator:
        save_channel_id(ctx.guild.id, channel.id)
        await ctx.followup.send(f'Channel set to {channel.mention}!', ephemeral=True)
    else:
        await ctx.followup.send('You must be an administrator to use this command.', ephemeral=True)

client.run(os.environ.get('DISCORD_BOT_TOKEN'))
