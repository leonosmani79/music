import os
import asyncio
import random
import time
import discord
from discord.ext import commands
from dotenv import load_dotenv
import yt_dlp

# --- LOAD .ENV HERE ---
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
print("TOKEN is:", repr(TOKEN))   # you can remove this once you're sure it's working

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- PATH TO FFMPEG ---
# 👉 Change this if your ffmpeg.exe is in a different folder
FFMPEG_EXE = r"C:\ffmpeg\bin\ffmpeg.exe"

# yt-dlp options
YDL_OPTIONS = {
    "format": "bestaudio/best",
    "quiet": True,
    "noplaylist": True
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn"
}


# ============================================
# MUSIC PLAYER CLASS
# ============================================
class MusicPlayer:
    def __init__(self):
        # each song is a dict: {"url", "title", "thumbnail", "channel", "duration"}
        self.queue = []
        self.loop = False          # loop current song
        self.autoloop = False      # loop queue
        self.current = None        # current song dict
        self.vc: discord.VoiceClient | None = None

        # panel & animation state
        self.panel_message: discord.Message | None = None
        self.panel_owner_id: int | None = None
        self._progress_task: asyncio.Task | None = None

    async def join_channel(self, ctx):
        if ctx.author.voice is None:
            await ctx.send("You must join a voice channel first.")
            return False

        channel = ctx.author.voice.channel

        if ctx.voice_client is None:
            self.vc = await channel.connect()
        else:
            self.vc = ctx.voice_client

        return True

    async def play_next(self, ctx):
        """Called automatically when a song finishes."""
        # If single-song loop is on, replay the same song
        if self.loop and self.current:
            await self.start_playing(ctx, self.current)
            return

        # No songs queued
        if not self.queue:
            self.current = None
            return

        # Take next song from queue
        self.current = self.queue.pop(0)

        # If autoloop is enabled, put the song back at the end of the queue
        if self.autoloop:
            self.queue.append(self.current)

        await self.start_playing(ctx, self.current)

    def build_now_playing_embed(
        self,
        requester: discord.Member | None = None,
        progress: float | None = None
    ) -> discord.Embed:
        """Build a stylish embed for the current song + queue/loop state."""
        if not self.current:
            embed = discord.Embed(
                title="🎶 Nothing is playing",
                description="Use `!play <song>` to start some music!",
                color=discord.Color.dark_gray()
            )
            return embed

        song = self.current
        title = song.get("title", "Unknown Title")
        url = song.get("url")
        thumbnail = song.get("thumbnail")
        channel = song.get("channel")
        duration = song.get("duration")

        embed = discord.Embed(
            title="**<a:Flicker:1444512741770662070>  Now Playing**",
            description=f"**[{title}]({url})**" if url else f"**{title}**",
            color=discord.Color.purple()
        )

        # Info row
        if channel:
            embed.add_field(name="<a:Flicker:1444512741770662070> Channel", value=channel, inline=True)

        if duration:
            mins = duration // 60
            secs = duration % 60
            embed.add_field(name="<a:Flicker:1444512741770662070> Duration", value=f"`{mins}:{secs:02d}`", inline=True)

        loop_state = "✅ ON" if self.loop else "❌ OFF"
        autoloop_state = "✅ ON" if self.autoloop else "❌ OFF"
        embed.add_field(name="<a:Flicker:1444512741770662070> Loop", value=loop_state, inline=True)
        embed.add_field(name="<a:Flicker:1444512741770662070> Autoloop", value=autoloop_state, inline=True)

        # Progress bar (this is what we "animate" by editing)
        if progress is not None and duration:
            bar_len = 20
            clamped = max(0.0, min(progress, 1.0))
            filled = int(bar_len * clamped)
            bar = "■" * filled + "□" * (bar_len - filled)

            pos_seconds = int(duration * clamped)
            mins = pos_seconds // 60
            secs = pos_seconds % 60

            embed.add_field(
                name="Progress",
                value=f"`[{bar}]` `{mins:02d}:{secs:02d}`",
                inline=False
            )
        else:
            embed.add_field(
                name="Progress",
                value="`[□□□□□□□□□□□□□□□□□□□□]`",
                inline=False
            )

        # Queue preview
        if self.queue:
            lines = []
            for i, s in enumerate(self.queue[:5], start=1):
                lines.append(f"`{i}.` {s.get('title','Unknown')}")
            more = ""
            if len(self.queue) > 5:
                more = f"\n… and `{len(self.queue) - 5}` more"

            embed.add_field(
                name=f"📜 Up Next ({len(self.queue)} in queue)",
                value="\n".join(lines) + more,
                inline=False
            )
        else:
            embed.add_field(
                name="📜 Up Next",
                value="Queue is empty.",
                inline=False
            )

        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        footer = "Use the buttons below to control the music 🎶"
        if requester:
            footer = f"Requested by {requester.display_name} • {footer}"
        embed.set_footer(text=footer)

        return embed

    async def start_playing(self, ctx, song):
        # Safe console logging (avoid UnicodeEncodeError in Windows)
        try:
            title_safe = (song.get("title") or "Unknown Title")
            title_safe = title_safe.encode("cp1252", errors="ignore").decode("cp1252", errors="ignore")
            print("Starting to play:", title_safe, song.get("url"))
        except Exception:
            print("Starting to play a song.")

        # Get direct audio stream URL with yt-dlp
        try:
            ydl = yt_dlp.YoutubeDL(YDL_OPTIONS)
            info = ydl.extract_info(song["url"], download=False)
            stream_url = info["url"]
        except Exception as e:
            print("yt-dlp error while getting stream URL:", e)
            await ctx.send("❌ Failed to get audio stream.")
            return

        # Create FFmpeg source (using explicit executable path)
        try:
            source = await discord.FFmpegOpusAudio.from_probe(
                stream_url,
                executable=FFMPEG_EXE,
                **FFMPEG_OPTIONS
            )
        except Exception as e:
            print("FFmpeg error while creating source:", e)
            await ctx.send("❌ FFmpeg error. Check your FFmpeg path in the code.")
            return

        def after_play(err):
            if err:
                print("Player error:", err)
            fut = asyncio.run_coroutine_threadsafe(self.play_next(ctx), bot.loop)
            try:
                fut.result()
            except Exception as e:
                print("Error in after_play future:", e)

        if self.vc:
            self.vc.play(source, after=after_play)

        # Start / restart the progress animation task
        if self._progress_task is not None and not self._progress_task.done():
            self._progress_task.cancel()
        self._progress_task = bot.loop.create_task(self._progress_updater())

    async def _progress_updater(self):
        """Background task that 'animates' the progress bar by editing the embed."""
        if not self.current:
            return

        duration = self.current.get("duration")
        if not duration or not isinstance(duration, (int, float)):
            return

        start = time.monotonic()

        while True:
            # stop animating if bot leaves or track finished
            if not self.vc or not self.vc.is_connected():
                break
            if not self.vc.is_playing() and not self.vc.is_paused():
                break

            elapsed = time.monotonic() - start
            progress = elapsed / duration

            if self.panel_message:
                try:
                    embed = self.build_now_playing_embed(progress=progress)
                    await self.panel_message.edit(embed=embed, view=self.panel_message.components and self.panel_message.components[0].view if hasattr(self.panel_message, "components") else None)
                except Exception as e:
                    print("Error updating progress:", e)

            await asyncio.sleep(5)  # update every 5 seconds

            if elapsed >= duration + 5:
                break


music = MusicPlayer()


# ============================================
# CONTROL PANEL VIEW (BUTTONS)
# ============================================
class MusicControlView(discord.ui.View):
    def __init__(self, music_player: MusicPlayer, owner_id: int):
        super().__init__(timeout=600)  # panel active for 10 minutes
        self.music = music_player
        self.owner_id = owner_id  # Only this user can control it

    def _allowed(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    async def refresh_panel(self, interaction: discord.Interaction):
        try:
            embed = self.music.build_now_playing_embed(requester=interaction.user)
            if self.music.panel_message:
                await self.music.panel_message.edit(embed=embed, view=self)
        except Exception as e:
            print("Error refreshing panel:", e)

    @discord.ui.button(label="Pause / Resume", style=discord.ButtonStyle.primary, emoji="⏯")
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            await interaction.response.send_message("Only the DJ who started this song can use these controls <a:Flicker:1444512741770662070>", ephemeral=True)
            return

        vc = self.music.vc
        if not vc:
            await interaction.response.send_message("I'm not connected to a voice channel. <a:Flicker:1444512741770662070>", ephemeral=True)
            return

        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Paused.", ephemeral=True)
        elif vc.is_paused():
            vc.resume()
            await interaction.response.send_message("▶️ Resumed.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing to pause or resume.", ephemeral=True)

        await self.refresh_panel(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.secondary, emoji="⏭")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            await interaction.response.send_message("Only the DJ can skip tracks.", ephemeral=True)
            return

        vc = self.music.vc
        if vc and vc.is_playing():
            self.music.loop = False
            vc.stop()
            await interaction.response.send_message("⏭ Skipped.", ephemeral=True)
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)

        await self.refresh_panel(interaction)

    @discord.ui.button(label="Loop Song", style=discord.ButtonStyle.secondary, emoji="🔁")
    async def loop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            await interaction.response.send_message("Only the DJ can change loop settings.", ephemeral=True)
            return

        self.music.loop = not self.music.loop
        state = "ON" if self.music.loop else "OFF"
        await interaction.response.send_message(f"🔁 Loop is now **{state}**.", ephemeral=True)
        await self.refresh_panel(interaction)

    @discord.ui.button(label="Autoloop Queue", style=discord.ButtonStyle.secondary, emoji="🔂")
    async def autoloop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            await interaction.response.send_message("Only the DJ can change autoloop.", ephemeral=True)
            return

        self.music.autoloop = not self.music.autoloop
        state = "ON" if self.music.autoloop else "OFF"
        await interaction.response.send_message(f"🔂 Autoloop is now **{state}**.", ephemeral=True)
        await self.refresh_panel(interaction)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="⏹")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self._allowed(interaction):
            await interaction.response.send_message("Only the DJ can stop the music.", ephemeral=True)
            return

        vc = self.music.vc
        if vc:
            self.music.loop = False
            self.music.queue.clear()
            vc.stop()
            await interaction.response.send_message("⏹ Stopped and cleared queue.", ephemeral=True)
        else:
            await interaction.response.send_message("I'm not playing anything.", ephemeral=True)

        await self.refresh_panel(interaction)


# ============================================
# BOT COMMANDS
# ============================================

@bot.command()
async def play(ctx, *, query):
    """Play a YouTube URL or search by keywords."""
    if not await music.join_channel(ctx):
        return

    await ctx.send("<a:Flicker:1444512741770662070> Searching...")

    # Search or use URL
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        try:
            # If not a URL, search on YouTube
            if not (query.startswith("http://") or query.startswith("https://")):
                info = ydl.extract_info(f"ytsearch:{query}", download=False)
                info = info["entries"][0]  # first result
            else:
                info = ydl.extract_info(query, download=False)
        except Exception as e:
            print("yt-dlp error in !play:", e)
            await ctx.send("❌ I couldn't find anything for that search.")
            return

    title = info.get("title", "Unknown Title")
    url = info["webpage_url"]
    song = {
        "url": url,
        "title": title,
        "thumbnail": info.get("thumbnail"),
        "channel": info.get("uploader"),
        "duration": info.get("duration"),
    }

    # if nothing is playing right now, start immediately
    if not music.vc or not music.vc.is_playing():
        music.current = song
        await music.start_playing(ctx, song)

        # 🎛 send stylish control panel + animated embed
        view = MusicControlView(music, owner_id=ctx.author.id)
        embed = music.build_now_playing_embed(requester=ctx.author, progress=0.0)
        msg = await ctx.send(embed=embed, view=view)
        music.panel_message = msg
        music.panel_owner_id = ctx.author.id
    else:
        # Otherwise, just queue it
        music.queue.append(song)
        await ctx.send(f"➕ Added to queue: **{title}**")


@bot.command()
async def skip(ctx):
    """Skip the current song."""
    if music.vc and music.vc.is_playing():
        music.loop = False
        music.vc.stop()
        await ctx.send("⏭ Skipped.")
    else:
        await ctx.send("Nothing is playing.")


@bot.command(aliases=["q"])
async def queue(ctx):
    """Show the queue."""
    if not music.queue:
        await ctx.send("Queue is empty.")
        return

    msg = "**🎵 Current Queue:**\n"
    for i, song in enumerate(music.queue, start=1):
        msg += f"{i}. {song.get('title', 'Unknown')}\n"

    await ctx.send(msg)


@bot.command()
async def shuffle(ctx):
    """Shuffle the current queue."""
    if len(music.queue) < 2:
        await ctx.send("Not enough songs in the queue to shuffle.")
        return

    random.shuffle(music.queue)
    await ctx.send("🔀 Shuffled the queue!")


@bot.command()
async def loop_cmd(ctx):
    """Toggle looping the current song."""
    music.loop = not music.loop
    await ctx.send(f"🔁 Loop is now **{'ON' if music.loop else 'OFF'}**")


@bot.command()
async def autoloop(ctx):
    """Toggle looping the entire queue forever."""
    music.autoloop = not music.autoloop
    await ctx.send(f"🔂 Autoloop is now **{'ON' if music.autoloop else 'OFF'}**")


@bot.command()
async def clear(ctx):
    """Clear the queue."""
    music.queue.clear()
    await ctx.send("🗑 Queue cleared.")


@bot.command(aliases=["np"])
async def nowplaying(ctx):
    """Show what's playing."""
    embed = music.build_now_playing_embed()
    await ctx.send(embed=embed)


@bot.command()
async def remove(ctx, index: int):
    """Remove a song from queue by number."""
    if index < 1 or index > len(music.queue):
        await ctx.send("**Invalid index.**")
        return

    removed = music.queue.pop(index - 1)
    await ctx.send(f"❌ Removed **{removed.get('title', 'Unknown')}** from queue.")


@bot.command()
async def stop(ctx):
    """Stop playback and clear."""
    if music.vc:
        music.loop = False
        music.queue.clear()
        music.vc.stop()
        await ctx.send("**⏹ Stopped.**")
    else:
        await ctx.send("**I'm not playing anything.**")


@bot.command()
async def leave(ctx):
    """Disconnect from voice."""
    if music.vc:
        await music.vc.disconnect()
        music.vc = None
        await ctx.send("👋 **Disconnected.**")
    else:
        await ctx.send("**Not connected.**")


# ============================================
bot.run(TOKEN)
