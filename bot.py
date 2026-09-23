import os
import sys
import time
import asyncio  # FIXED: Added to handle non-blocking asynchronous delays
import io
import requests

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
# Yapısı: { user_id: [ {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."} ] }
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
    
    # 1. IMMEDIATE FILTER: Completely ignore any message sent by a bot account (prevents duplicate loops)
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
            # OPTIONAL FEATURE: Detect if the user wants an image generated
            image_keywords = ["create an image", "generate an image", "draw", "paint", "imagine", "make a picture", "resim çiz", "resim oluştur"]
            is_image_request = any(keyword in prompt.lower() for keyword in image_keywords)

            if is_image_request:
                logger.info("Executing image generation pipeline...")
                image_response = client_ai.images.generate(
                    model="gpt-image-2.5-flare",  # High-speed image creator model
                    prompt=prompt,
                    n=1,
                    size="1024x1024",
                    quality="standard"  # Keeps token footprint lean
                )
                image_url = image_response.data[0].url
                
                # Download it natively into memory to upload directly to Discord
                img_data = requests.get(image_url).content
                image_file = nextcord.File(io.BytesIO(img_data), filename="generated_image.png")
                response_text = f"🎨 Here is your generated image for: *\"{prompt}\"*:"
            
            else:
                # ─── HAFIZALI STANDART METİN TAMAMLAMA SİSTEMİ ───
                # 1. Kullanıcının daha önce hafızası yoksa yeni bir liste oluştur
                if user_id not in USER_MEMORY:
                    USER_MEMORY[user_id] = []

                # 2. Kullanıcının yeni yazdığı mesajı kendi hafıza havuzuna ekle
                USER_MEMORY[user_id].append({"role": "user", "content": prompt})

                # 3. OpenAI'a gönderilecek mesaj listesini hazırla (Önce Sistem Talimatı)
                messages_payload = [
                    { 
                        "role": "system", 
                        "content": "You are a helpful and intelligent Discord AI assistant powered by GPT-5.4-Mini. You remember the ongoing conversation history with the user. Answer questions clearly, accurately, and natively in the user's language." 
                    }
                ]
                
                # Sistem talimatının ardına kullanıcının geçmiş hafıza listesini ekle
                messages_payload.extend(USER_MEMORY[user_id])

                response = client_ai.chat.completions.create(
                    model='gpt-5.4-mini',
                    max_completion_tokens=1900,
                    n=1,
                    stop=None,
                    temperature=0.7,  # Hafızalı sohbette daha tutarlı cevaplar için 0.7 idealdir
                    messages=messages_payload
                )
                # DÜZELTME: API Nesnesi modern hiyerarşiye uygun olarak çağrıldı
                response_text = response.choices.message.content
                
                # 4. Yapay zekanın verdiği cevabı da kullanıcının hafızasına ekle
                USER_MEMORY[user_id].append({"role": "assistant", "content": response_text})

                # 5. Hafıza şişip cüzdanı bitirmesin diye son limit mesajdan eskisini kırp
                if len(USER_MEMORY[user_id]) > MAX_MEMORY_LIMIT:
                    USER_MEMORY[user_id] = USER_MEMORY[user_id][-MAX_MEMORY_LIMIT:]
                
                # Print exact usage metrics directly into Railway logs to track token footprint
                logger.info(f"📊 [OpenAI Usage Tracker] -> {response.usage}")

        except Exception as e:
            logger.error(f"OpenAI API Hatasi: {e}")
            response_text = f"**⚠️ OpenAI API Hatası! Detay: {e}**"

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
                    # FIXED: Keeps the execution thread fully open/asynchronous so Discord doesn't resend the event
                    await asyncio.sleep(0.5)  
            else:
                await message.reply(response_text)

        end_time = int(time.time() * 1000)
        logger.success(f'Responded to a prompt in {end_time - start_time}ms!')

# Slash command configuration for setting up the active listening channel
@client.slash_command(name='set_channel', description='Set the channel where the client listens for messages')
async def set_channel(ctx, channel: nextcord.TextChannel):
    await ctx.response.defer(ephemeral=True)
    
    if ctx.user.guild_permissions.administrator:
        save_channel_id(ctx.guild.id, channel.id)
        await ctx.followup.send(f'Channel set to {channel.mention}!', ephemeral=True)
    else:
        await ctx.followup.send('You must be an administrator to use this command.', ephemeral=True)

client.run(os.environ.get('DISCORD_BOT_TOKEN'))
