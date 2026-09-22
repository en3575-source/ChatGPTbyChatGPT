import os
import sys
import time

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
    if str(message.channel.id) == str(get_channel_id(message.guild.id)) and message.author.id != client.user.id and not (message.content.startswith('#') or message.content.startswith('.') or message.content.startswith('<')):
        async with message.channel.typing():
            start_time = int(time.time() * 1000)
            prompt = message.clean_content
            logger.info(f'Got prompt: "{prompt}"')

            try:
                # GÜNCEL KUTUPHANE STANDARDI: v1.0.0+ uyumlu chat completions yapısı
                response = client_ai.chat.completions.create(
                    model='gpt-5.4-mini',
                    max_completion_tokens=1900,
                    n=1,
                    stop=None,
                    temperature=1.0,
                    messages=[
                        # TEMİZLENMİŞ SİSTEM TALİMATI: Tüm gizli reklamlar ve eski kurallar tamamen kaldırıldı!
                        { "role": "system", "content": "You are a helpful and intelligent Discord AI assistant powered by GPT-5.4-Mini. Answer questions clearly, accurately, and natively in the user's language." },
                        {"role":"user", "content":prompt}
                    ]
                )
                # DÜZELTME: API Nesnesi doğru hiyerarşide çağrılacak şekilde eklendi
                response_text = response.choices[0].message.content
            except Exception as e:
                logger.error(f"OpenAI API Hatasi: {e}")
                response_text = f"**⚠️ OpenAI API Hatası! Detay: {e}**"

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
            # DÜZELTME: Metin 2000 karakterden uzunsa otomatik parçalara bölerek sırayla gönderir
            if len(response_text) > 2000:
                chunks = [response_text[i:i+1900] for i in range(0, len(response_text), 1900)]
                for chunk in chunks:
                    await message.reply(chunk)
                    time.sleep(0.5)  # Discord Rate Limit'e takılmamak için kısa bekleme süresi
            else:
                await message.reply(response_text)

        end_time = int(time.time() * 1000)
        logger.success(f'Responded to a prompt in {end_time - start_time}ms!')

# DÜZELTME: Discord'un 3 saniyelik zaman aşımına düşmemesi için Slash Komut yapısı baştan tasarlandı
@client.slash_command(name='set_channel', description='Set the channel where the client listens for messages')
async def set_channel(ctx, channel: nextcord.TextChannel):
    # Discord'a "komutu aldım, işlem yapıyorum" sinyali göndererek zaman aşımı hatasını engeller
    await ctx.response.defer(ephemeral=True)
    
    if ctx.user.guild_permissions.administrator:
        save_channel_id(ctx.guild.id, channel.id)
        # Defer kullandığımız için send yerine followup.send ile yanıt veriyoruz
        await ctx.followup.send(f'Channel set to {channel.mention}!', ephemeral=True)
    else:
        await ctx.followup.send('You must be an administrator to use this command.', ephemeral=True)

client.run(os.environ.get('DISCORD_BOT_TOKEN'))
