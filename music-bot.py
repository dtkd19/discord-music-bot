import discord
from discord.ext import commands
import yt_dlp
import asyncio
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()

# 환경 변수에서 토큰 가져오기
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


TARGET_CHANNEL_IDS = [1339069701527044149, 1250860258604351654, 1339803258155307130]

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1:',
    'source_address': '0.0.0.0'
}

ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')

    @classmethod
    async def from_query(cls, query, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=not stream))
        
        if 'entries' in data:
            data = data['entries'][0]

        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

playlist = []
current_song = None
current_song_message = None  # 현재 재생 중인 곡 embed 메시지 객체
playlist_embed_messages = []  # 플레이리스트 embed 메시지 객체들을 저장

@bot.event
async def on_message(message):
    global current_song, current_song_message
    if message.author.bot:
        return

    if message.channel.id not in TARGET_CHANNEL_IDS:
        return
    
    if not message.author.voice or not message.author.voice.channel:
        await message.channel.send("음성 채널에 먼저 입장해주세요.")
        return

    channel = message.author.voice.channel
    voice_client = discord.utils.get(bot.voice_clients, guild=message.guild)
    if not voice_client:
        voice_client = await channel.connect()

    async with message.channel.typing():
        player = await YTDLSource.from_query(message.content, loop=bot.loop, stream=True)
        if not voice_client.is_playing() and not voice_client.is_paused():
            current_song = player
            voice_client.play(player, after=lambda e: bot.loop.create_task(play_next_song(voice_client)))
        else:
            # 재생 중인 곡이 있으면 플레이리스트에 추가
            playlist.append(player)
            confirmation = await message.channel.send(f"🎶 **{player.title}**이(가) 플레이리스트에 추가되었습니다.")
            await asyncio.sleep(3)  # 3초 후에 삭제 (원하는 시간으로 조절)
            await confirmation.delete()

    # 버튼 구성
    buttons = [
        discord.ui.Button(label="재생", style=discord.ButtonStyle.green, custom_id="resume"),
        discord.ui.Button(label="멈춤", style=discord.ButtonStyle.red, custom_id="pause"),
        discord.ui.Button(label="스킵", style=discord.ButtonStyle.blurple, custom_id="skip"),
        discord.ui.Button(label="플레이리스트", style=discord.ButtonStyle.grey, custom_id="playlist"),
        discord.ui.Button(label="플레이리스트 수정", style=discord.ButtonStyle.blurple, custom_id="playlist_edit")
    ]
    view = discord.ui.View()
    for button in buttons:
        view.add_item(button)

    # 현재 재생곡 embed 생성
    embed = discord.Embed(title=f"🎵 현재 재생: {current_song.title}", color=0x1abc9c)
    if current_song.data.get("thumbnail"):
        embed.set_image(url=current_song.data["thumbnail"])

    # 기존 embed 메시지 삭제 (이미 있으면)
    if current_song_message:
        try:
            await current_song_message.delete()
        except Exception:
            pass

    current_song_message = await message.channel.send(embed=embed, view=view)
    
    # 노래 등록용 사용자의 메시지도 삭제 (자연스러운 채팅 정리를 위해)
    try:
        await message.delete()
    except Exception:
        pass

async def play_next_song(voice_client):
    global current_song, current_song_message, playlist_embed_messages
    
    # [수정 1] 현재 봇이 있는 텍스트 채널 찾기
    text_channel = None
    for channel in bot.get_all_channels():
        if isinstance(channel, discord.TextChannel) and channel.id in TARGET_CHANNEL_IDS:
            text_channel = channel
            break
    
    if playlist:
        next_song = playlist.pop(0)  # 한 곡만 pop(0)으로 재생
        current_song = next_song
        voice_client.play(next_song, after=lambda e: bot.loop.create_task(play_next_song(voice_client)))
        
        # [수정 2] 플레이리스트 메시지 삭제 및 갱신
        if playlist_embed_messages:
            try:
                for msg in playlist_embed_messages:
                    await msg.delete()  # 플레이리스트 메시지 삭제
            except:
                pass
            playlist_embed_messages.clear()  # 메시지 목록 초기화

        # 새 Embed 생성
        embed = discord.Embed(title=f"🎵 현재 재생: {current_song.title}", color=0x1abc9c)
        if current_song.data.get("thumbnail"):
            embed.set_image(url=current_song.data["thumbnail"])

        buttons = [
            discord.ui.Button(label="재생", style=discord.ButtonStyle.green, custom_id="resume"),
            discord.ui.Button(label="멈춤", style=discord.ButtonStyle.red, custom_id="pause"),
            discord.ui.Button(label="스킵", style=discord.ButtonStyle.blurple, custom_id="skip"),
            discord.ui.Button(label="플레이리스트", style=discord.ButtonStyle.grey, custom_id="playlist"),
            discord.ui.Button(label="플레이리스트 수정", style=discord.ButtonStyle.blurple, custom_id="playlist_edit")
        ]
        view = discord.ui.View()
        for button in buttons:
            view.add_item(button)

        try:
            if current_song_message:
                await current_song_message.edit(embed=embed, view=view)
            else:
                if text_channel:
                    current_song_message = await text_channel.send(embed=embed, view=view)
        except discord.NotFound:
            if text_channel:
                current_song_message = await text_channel.send(embed=embed, view=view)

    else:
        current_song = None
        if current_song_message:
            try:
                await current_song_message.delete()
            except:
                pass
            current_song_message = None
        
        if text_channel:
            msg = await text_channel.send("🎶 모든 노래가 끝났습니다.")
            await asyncio.sleep(3)
            await msg.delete()

@bot.event
async def on_interaction(interaction):
    global current_song, current_song_message, playlist_embed_messages
    if interaction.type == discord.InteractionType.component:
        custom_id = interaction.data.get("custom_id")
        voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
        
        if custom_id == "pause":
            if voice_client.is_playing():
                voice_client.pause()
                response = await interaction.response.send_message("⏸️ 일시정지 되었습니다.")
                await asyncio.sleep(3)
                await response.delete()
            else:
                response = await interaction.response.send_message("❗ 재생 중인 노래가 없습니다.")
                await asyncio.sleep(3)
                await response.delete()
        
        elif custom_id == "resume":
            if voice_client.is_paused():
                voice_client.resume()
                response = await interaction.response.send_message("▶️ 재생을 재개합니다.")
                await asyncio.sleep(3)
                await response.delete()
            else:
                response = await interaction.response.send_message("❗ 일시정지 상태가 아닙니다.")
                await asyncio.sleep(3)
                await response.delete()
    
        elif custom_id == "skip":
            if voice_client.is_playing() or voice_client.is_paused():
                voice_client.stop()
                # voice_client.stop()이 after 콜백을 호출하므로, 여기서 play_next_song을 직접 호출할 필요가 없습니다.
                await interaction.response.send_message("⏭️ 곡을 스킵합니다...", delete_after=2)
            else:
                await interaction.response.send_message("❗ 재생 중인 곡이 없습니다.", delete_after=3)


        elif custom_id == "playlist":
            if playlist:
                playlist_titles = "\n".join(f"{i+1}. {song.title}" for i, song in enumerate(playlist))
                embed = discord.Embed(title="📜 플레이리스트", description=playlist_titles, color=0x1abc9c)
                # 첫 번째 응답으로 바로 보내면 추가 followup이 필요없습니다.
                await interaction.response.send_message(embed=embed)
                # 만약 나중에 이 메시지를 삭제하고 싶다면, 봇이 보낸 메시지를 따로 저장하는 방법이 필요합니다.
            else:
                response = await interaction.response.send_message("📜 플레이리스트가 비어있습니다.")
                await asyncio.sleep(3)
                await response.delete()     
        
        elif custom_id == "playlist_edit":
            if playlist:
                options = [
                    discord.SelectOption(label=f"{song.title}", value=str(i))
                    for i, song in enumerate(playlist)
                ]
                select = discord.ui.Select(
                    placeholder="삭제할 곡을 선택하세요.",
                    min_values=1,
                    max_values=1,
                    options=options
                )

                async def select_callback(interaction):
                    index = int(select.values[0])
                    song_to_delete = playlist.pop(index)
                    delete_message = await interaction.response.send_message(
                        f"🎶 **{song_to_delete.title}** 이(가) 플레이리스트에서 삭제되었습니다."
                    )
                    await asyncio.sleep(3)
                    await delete_message.delete()  # 3초 후 삭제

                    if playlist:
                        playlist_titles = "\n".join(f"{i+1}. {song.title}" for i, song in enumerate(playlist))
                        embed = discord.Embed(title="🎶 플레이리스트", description=playlist_titles, color=0x1abc9c)
                        playlist_message = await interaction.followup.send(embed=embed)
                        await asyncio.sleep(3)
                        await playlist_message.delete()  # 3초 후 삭제
                    else:
                        empty_message = await interaction.followup.send("📜 플레이리스트가 비어있습니다.")
                        await asyncio.sleep(3)
                        await empty_message.delete()  # 3초 후 삭제

                select.callback = select_callback
                view = discord.ui.View()
                view.add_item(select)

                select_message = await interaction.response.send_message("삭제할 곡을 선택하세요:", view=view)
                await asyncio.sleep(10)  # 10초 동안 유지 후 삭제
                await select_message.delete()  # 드롭다운 메시지 삭제
            else:
                no_playlist_message = await interaction.response.send_message("❗ 플레이리스트에 노래가 없습니다.")
                await asyncio.sleep(3)
                await no_playlist_message.delete()  # 3초 후 삭제

bot.run(TOKEN)