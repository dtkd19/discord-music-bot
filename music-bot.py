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
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)


TARGET_CHANNEL_IDS = [1339069701527044149, 1250860258604351654, 1339803258155307130, 1340382563830730813]

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
    'source_address': '0.0.0.0',
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
        # URL인지 체크: 'http://' 또는 'https://'로 시작하면 URL로 판단
        if query.startswith("http://") or query.startswith("https://"):
            info = await loop.run_in_executor(None, lambda: ytdl.extract_info(query, download=not stream))
        else:
            info = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=not stream))
        
        if 'entries' in info:
            info = info['entries'][0]

        filename = info['url'] if stream else ytdl.prepare_filename(info)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=info)

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

def get_related_videos(video_id):
    url = f"https://www.youtube.com/watch?v={video_id}"
    ydl_opts = {
        'quiet': True,
        'extract_flat': False,
        'force_generic_extractor': False,
        'compat_opts': {'no-youtube-channel-redirect': True},
        'extract_args': {'skip_download': True}
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            related_videos = []
            if 'related_videos' in info:
                related_videos = info['related_videos']
            elif 'entries' in info:
                related_videos = info['entries']
            
            # 웹페이지 파싱 (requests 사용)
            if not related_videos:
                print("[DEBUG] requests로 웹페이지 파싱 시도")
                import requests
                import re  # 정규식 사용을 위해 추가
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
                response = requests.get(url, headers=headers)
                response.raise_for_status()
                webpage = response.text
                
                # 정규식으로 ytInitialData 추출
                initial_data_str = re.search(
                    r'ytInitialData\s*=\s*({.+?});', 
                    webpage, 
                    re.DOTALL
                )
                if initial_data_str:
                    initial_data_str = initial_data_str.group(1)
                    import json
                    initial_data = json.loads(initial_data_str)
                    # 관련 영상 경로 확인 필요
                    related_items = initial_data.get('contents', {}).get('twoColumnWatchNextResults', {}).get('secondaryResults', {}).get('secondaryResults', {}).get('results', [])
                    for item in related_items:
                        if 'compactVideoRenderer' in item:
                            video = item['compactVideoRenderer']
                            video_id = video.get('videoId')
                            title_runs = video.get('title', {}).get('runs', [{}])
                            title = title_runs[0].get('text', '제목 없음') if title_runs else '제목 없음'
                            related_videos.append({
                                'id': video_id,
                                'title': title,
                                'url': f"https://youtube.com/watch?v={video_id}"
                            })
                else:
                    print("[ERROR] ytInitialData를 찾을 수 없음")

            return [
                entry
                for entry in related_videos[:5]
                if entry.get('id') and entry.get('id') != video_id
            ]
            
    except Exception as e:
        print(f"[ERROR] 관련 영상 추출 실패: {str(e)}")
        return []

async def play_next_song(voice_client):
    global current_song, current_song_message, playlist_embed_messages
    
    # 텍스트 채널 찾기
    text_channel = None
    for channel in bot.get_all_channels():
        if isinstance(channel, discord.TextChannel) and channel.id in TARGET_CHANNEL_IDS:
            text_channel = channel
            break

    if playlist:
        next_song = playlist.pop(0)  # 플레이리스트에 있으면 다음 곡 재생
        current_song = next_song
        voice_client.play(next_song, after=lambda e: bot.loop.create_task(play_next_song(voice_client)))
        
        # 플레이리스트 관련 메시지 삭제 및 초기화
        if playlist_embed_messages:
            for msg in playlist_embed_messages:
                try:
                    await msg.delete()
                except:
                    pass
            playlist_embed_messages.clear()
    else:
        if current_song:
            current_video_id = current_song.data.get("id")
            if not current_video_id:
                current_video_id = extract_video_id(current_song.url)

            # 디버깅 메시지 전송 (채널에 표시)
            debug_embed = discord.Embed(title="🔍 디버깅 정보", color=0xffd700)
            debug_embed.add_field(name="현재 영상 ID", value=f"`{current_video_id}`", inline=False)
            
            related_videos = get_related_videos(current_video_id)
            debug_embed.add_field(
                name="찾은 관련 영상", 
                value=f"개수: {len(related_videos)}\n" + "\n".join([f"- {v['title']} ({v['id']})" for v in related_videos[:3]]),
                inline=False
            )

            if related_videos:
                next_video = related_videos[0]  # 첫 번째 영상 선택
                video_url = next_video['url']
                print(f"다음 재생 시도 URL: {video_url}")

                try:
                    next_song = await YTDLSource.from_query(video_url, loop=bot.loop, stream=True)
                    current_song = next_song
                    voice_client.play(next_song, after=lambda e: bot.loop.create_task(play_next_song(voice_client)))
                except Exception as e:
                    if text_channel:
                        error_msg = await text_channel.send("❗ 자동재생에 실패했습니다. 다시 시도해주세요.")
                        await asyncio.sleep(3)
                        await error_msg.delete()
                        current_song = None
                    if current_song_message:
                        try:
                            await current_song_message.delete()
                        except:
                            pass
                        return
            else:
                if text_channel:
                    msg = await text_channel.send("🎶 관련 영상을 찾을 수 없습니다.")
                    await asyncio.sleep(3)
                    await msg.delete()

        else:
            if text_channel:
                msg = await text_channel.send("🎶 모든 노래가 끝났습니다.")
                await asyncio.sleep(3)
                await msg.delete()
            return

    # 새 Embed 생성 및 버튼 업데이트
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
        elif text_channel:
            current_song_message = await text_channel.send(embed=embed, view=view)
    except discord.NotFound:
        if text_channel:
            current_song_message = await text_channel.send(embed=embed, view=view)

def extract_video_id(url):
    """유튜브 URL로부터 videoId를 추출하는 간단한 함수 (필요 시 개선)"""
    import re
    pattern = r"(?:v=|\/)([0-9A-Za-z_-]{11}).*"
    match = re.search(pattern, url)
    if match:
        return match.group(1)
    return None

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