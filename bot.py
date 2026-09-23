import os
import sys
import time
import asyncio
import io
import aiohttp
import urllib.parse

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

# API İstemci Kurulumu (Resmi OpenAI v1.0.0+ Standart)
client_ai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

intents = nextcord.Intents.default()
intents.guild_messages = True
intents.message_content = True

client = nextcord.Client(intents=intents)

# --- AKILLI VE EKONOMİK HAFIZA SİSTEMİ ALTYAPISI ---
USER_MEMORY = {}
MAX_MEMORY_LIMIT = 10  # Hafızada tutulacak maksimum mesaj sınırı (Prompt Caching ile %90 indirimli)

def save_channel_id(guild_id, channel_id):
    storage = {'guilds': {}}
    if os.path.exists('storage.yml'):
        with open('storage.yml', 'r') as f:
            storage = yaml.safe_load(f)
    storage['guilds'][str(guild_id)] = {'channel_id': str(channel_id)}
    with open('storage.yml', 'w') as f:
        yaml.dump(storage, f)

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
    
    if message.author.bot:
        return

    target_channel_id = get_channel_id(message.guild.id)
    if not target_channel_id or str(message.channel.id) != str(target_channel_id):
        return

    if message.content.startswith(('#', '.', '<')):
        return

    async with message.channel.typing():
        start_time = int(time.time() * 1000)
        prompt = message.content
        user_id = message.author.id
        logger.info(f'Got prompt from User {user_id}: "{prompt}"')

        # Resim isteklerini kontrol et
        image_keywords = ["draw", "paint", "image", "picture", "resim", "ciz", "çiz", "görsel", "gorsel"]
        is_image_request = any(keyword in prompt.lower() for keyword in image_keywords)

        if is_image_request:
            logger.info("Executing official OpenAI modern image pipeline...")
            try:
                # Kullanıcının metnini küçük harfe çevirip komut kelimelerini ayıklıyoruz
                clean_text = prompt.lower()
                clean_text = clean_text.replace(f"@{client.user.name.lower()}", "")
                for keyword in image_keywords:
                    clean_text = clean_text.replace(keyword, "")
                clean_text = clean_text.replace(":", "").strip()
                
                if not clean_text:
                    clean_text = "fantasy landscape"

                # Resmi OpenAI model bağlantısı
                image_response = client_ai.images.generate(
                    model="gpt-image-1-mini",
                    prompt=clean_text,
                    n=1,
                    size="1024x1024"
                )
                
                image_url = image_response.data[0].url
                logger.info(f"Successfully retrieved image URL: {image_url}")
                
                # Resmi asenkron olarak indirip disk üzerine fiziksel dosya olarak kaydediyoruz
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url, timeout=20) as response:
                        if response.status == 200:
                            img_data = await response.read()
                            
                            # KESİN DÜZELTME: Resmi sunucu diskine fiziksel bir .png dosyası olarak yazıyoruz
                            local_file_path = "generated_image.png"
                            with open(local_file_path, "wb") as f:
                                f.write(img_data)
                            
                            # KESİN DÜZELTME: Nextcord'a doğrudan fiziksel dosyanın metinsel yolunu ("generated_image.png") 
                            # parametre olarak veriyoruz. Böylece "parameter should be str" kuralı %100 karşılanmış oluyor!
                            image_file = nextcord.File(local_file_path)
                            
                            await message.reply(content=f"🎨 Here is your image for: *\"{clean_text}\"*:", file=image_file)
                            
                            # İşlem bitince sunucu hafızasında çöp birikmesin diye geçici dosyayı siliyoruz
                            if os.path.exists(local_file_path):
                                os.remove(local_file_path)
                        else:
                            await message.reply("⚠️ Görsel Discord'a yüklenirken geçici bir sorun oluştu.")
                return

            except Exception as e:
                logger.error(f"Image Pipeline Hatasi: {e}")
                await message.reply(f"**⚠️ Resim oluşturulurken bir hata oluştu! Detay: {e}**")
                return

        # ─── HAFIZALI STANDART METİN TAMAMLAMA SİSTEMİ ───
        try:
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
            
            if not response_text.startswith('#NORESPOND'):
                if len(response_text) > 2000:
                    chunks = [response_text[i:i+1900] for i in range(0, len(response_text), 1900)]
                    for chunk in chunks:
                        await message.reply(chunk)
                        await asyncio.sleep(0.5)  
                else:
                    await message.reply(response_text)

        except Exception as e:
            logger.error(f"Sohbet API Hatasi: {e}")
            await message.reply(f"**⚠️ OpenAI API Hatası! Detay: {e}**")

        end_time = int(time.time() * 1000)
        logger.success(f'Responded to a prompt in {end_time - start_time}ms!')

@client.slash_command(name='set_channel', description='Set the channel where the client listens for messages')
async def set_channel(ctx, channel: nextcord.TextChannel):
    await ctx.response.defer(ephemeral=True)
    if ctx.user.guild_permissions.administrator:
        save_channel_id(ctx.guild.id, channel.id)
        await ctx.followup.send(f'Channel set to {channel.mention}!', ephemeral=True)
    else:
        await ctx.followup.send('You must be an administrator to use this command.', ephemeral=True)

client.run(os.environ.get('DISCORD_BOT_TOKEN'))
