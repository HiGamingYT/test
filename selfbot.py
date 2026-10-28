#!/usr/bin/env python3
"""
discord.py-self command bot with 300 commands in 8 categories.

Setup
-----
    pip install discord.py-self
    export DISCORD_TOKEN="your-account-token"      # Windows: set DISCORD_TOKEN=...
    python selfbot.py

Optional environment variables
    BOT_PREFIX   command prefix (default "!")
    DATA_FILE    where notes/todos/warns are stored (default selfbot_data.json)

WARNING: automating a user account ("self-botting") violates Discord's Terms
of Service and can get the account disabled. Use a throwaway/test account,
never share the token, and keep the token out of source control.

Only messages sent BY THE LOGGED-IN ACCOUNT are treated as commands, so other
people cannot trigger anything by typing "!ban" in chat.

Categories (50 + 35 + 40 + 40 + 35 + 35 + 40 + 25 = 300)
    Roleplay, Moderation, Fun, Text, Math, Info, Utility, Generators
Run !help, !help <category> or !help <command> in Discord.
"""
import ast
import asyncio
import base64
import codecs
import functools
import hashlib
import html
import json
import math
import operator
import os
import platform
import random
import re
import secrets
import statistics
import string
import sys
import time
import unicodedata
import uuid
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

import discord
from discord.ext import commands

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
TOKEN = os.getenv("DISCORD_TOKEN")
PREFIX = os.getenv("BOT_PREFIX", "!")
DATA_FILE = Path(os.getenv("DATA_FILE", "selfbot_data.json"))
START_TIME = time.time()

bot = commands.Bot(command_prefix=PREFIX, help_command=None)

REGISTRY = {}      # category -> [command names]
CATEGORY_OF = {}   # command name -> category
TASKS = set()      # keeps background tasks (reminders) alive
SNIPES = {}        # channel id -> deleted message info
EDIT_SNIPES = {}   # channel id -> edited message info
STOPWATCH = {"start": None, "laps": []}


# --------------------------------------------------------------------------
# Persistent storage (notes, todos, bookmarks, warns)
# --------------------------------------------------------------------------
def load_data():
    try:
        return json.loads(DATA_FILE.read_text("utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


DB = load_data()


def save_data():
    DATA_FILE.write_text(json.dumps(DB, indent=2, ensure_ascii=False), "utf-8")


# --------------------------------------------------------------------------
# Registration helpers
# --------------------------------------------------------------------------
def command(category, name, **kwargs):
    """Decorator: register a command and file it under a category."""
    def deco(fn):
        cmd = bot.command(name=name, **kwargs)(fn)
        REGISTRY.setdefault(category, []).append(name)
        CATEGORY_OF[name] = category
        return cmd
    return deco


def register(category, name, callback, help_text=""):
    """Register a command built dynamically by a factory function."""
    cmd = commands.Command(callback, name=name, help=help_text)
    bot.add_command(cmd)
    REGISTRY.setdefault(category, []).append(name)
    CATEGORY_OF[name] = category
    return cmd


# --------------------------------------------------------------------------
# Generic helpers
# --------------------------------------------------------------------------
async def say(ctx, text):
    """Reply with mentions neutralised, split to fit Discord's 2000 limit."""
    text = discord.utils.escape_mentions(str(text)) or "\u200b"
    for i in range(0, len(text), 1990):
        await ctx.reply(text[i:i + 1990], mention_author=False)


def codeblock(text, lang=""):
    return "```{}\n{}\n```".format(lang, str(text).replace("```", "`\u200b``"))


def get_ref(ctx):
    ref = ctx.message.reference
    if ref and isinstance(ref.resolved, discord.Message):
        return ref.resolved
    return None


def get_text(ctx, text):
    """Use the given text, or the content of the replied-to message."""
    if text and text.strip():
        return text
    ref = get_ref(ctx)
    return ref.content if ref else ""


def fmt_num(x):
    if isinstance(x, float):
        return "{:.10g}".format(x)
    return str(x)


def parse_duration(text):
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    return sum(int(n) * units[u] for n, u in re.findall(r"(\d+)\s*([smhdw])", text.lower()))


def human_duration(seconds):
    seconds = int(seconds)
    parts = []
    for label, size in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append("{}{}".format(value, label))
    return " ".join(parts) or "0s"


def fmt_dt(dt):
    ts = int(dt.timestamp())
    return "<t:{}:F> (<t:{}:R>)".format(ts, ts)


def parse_date(text):
    text = text.strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d.%m.%Y", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError("use YYYY-MM-DD (optionally followed by HH:MM)")


def spawn(coro):
    task = asyncio.ensure_future(coro)
    TASKS.add(task)
    task.add_done_callback(TASKS.discard)
    return task


def to_int(x):
    if x != int(x):
        raise ValueError("an integer is required")
    return int(x)


# ==========================================================================
# 1) ROLEPLAY  (50)
# ==========================================================================
ROLEPLAY = [
    ("hug", "hugs", "🤗", "hugs themselves"),
    ("kiss", "kisses", "😘", "blows a kiss"),
    ("pat", "pats", "🖐️", "pats the air"),
    ("cuddle", "cuddles", "🥰", "cuddles a pillow"),
    ("poke", "pokes", "👉", "pokes the void"),
    ("slap", "playfully slaps", "🖐️", "slaps the table"),
    ("bite", "nibbles", "😬", "nibbles a snack"),
    ("boop", "boops", "👆", "boops the air"),
    ("tickle", "tickles", "🤭", "giggles uncontrollably"),
    ("wave", "waves at", "👋", "waves at everyone"),
    ("highfive", "high-fives", "✋", "high-fives the air"),
    ("dance", "dances with", "💃", "dances alone"),
    ("cry", "cries with", "😢", "cries quietly"),
    ("laugh", "laughs with", "😂", "laughs out loud"),
    ("blush", "blushes at", "😳", "blushes"),
    ("smile", "smiles at", "😊", "smiles warmly"),
    ("pout", "pouts at", "🥺", "pouts"),
    ("shrug", "shrugs at", "🤷", "shrugs"),
    ("facepalm", "facepalms at", "🤦", "facepalms"),
    ("wink", "winks at", "😉", "winks"),
    ("sleep", "falls asleep on", "😴", "falls asleep"),
    ("bonk", "bonks", "🔨", "bonks themselves"),
    ("yeet", "yeets", "🚀", "yeets a chair"),
    ("punch", "playfully punches", "👊", "shadowboxes"),
    ("punt", "punts", "🦵", "kicks a rock"),
    ("stare", "stares at", "👀", "stares into the distance"),
    ("salute", "salutes", "🫡", "salutes"),
    ("bow", "bows to", "🙇", "bows"),
    ("clap", "claps for", "👏", "claps"),
    ("cheer", "cheers for", "🎉", "cheers"),
    ("handhold", "holds hands with", "🤝", "holds their own hands"),
    ("feed", "feeds", "🍜", "eats a snack"),
    ("glare", "glares at", "😒", "glares at nothing"),
    ("nuzzle", "nuzzles", "🥹", "nuzzles a blanket"),
    ("snuggle", "snuggles", "🧸", "snuggles a plushie"),
    ("tackle", "tackles", "🏈", "tackles the air"),
    ("pillow", "throws a pillow at", "🛏️", "throws a pillow"),
    ("carry", "carries", "🏃", "carries nobody"),
    ("spin", "spins", "🌀", "spins around"),
    ("protect", "protects", "🛡️", "stands guard"),
    ("comfort", "comforts", "🫂", "takes a deep breath"),
    ("fistbump", "fist-bumps", "🤜", "fist-bumps the air"),
    ("thumbsup", "gives a thumbs up to", "👍", "gives a thumbs up"),
    ("think", "thinks about", "🤔", "thinks deeply"),
    ("panic", "panics at", "😱", "panics"),
    ("flex", "flexes on", "💪", "flexes"),
    ("sing", "sings to", "🎤", "sings"),
    ("whisper", "whispers to", "🤫", "whispers"),
    ("gift", "gifts a present to", "🎁", "wraps a present"),
    ("bless", "blesses", "✨", "glows softly"),
]


def make_roleplay(verb, solo, emoji):
    async def callback(ctx, *, target: str = ""):
        actor = ctx.author.display_name
        if ctx.message.mentions:
            who = " and ".join(m.display_name for m in ctx.message.mentions)
            text = "*{} {} {}* {}".format(actor, verb, who, emoji)
        elif target.strip():
            text = "*{} {} {}* {}".format(actor, verb, target.strip(), emoji)
        else:
            text = "*{} {}* {}".format(actor, solo, emoji)
        await say(ctx, text)
    return callback


for _name, _verb, _emoji, _solo in ROLEPLAY:
    register("Roleplay", _name, make_roleplay(_verb, _solo, _emoji),
             "{} someone (or no one). Usage: {}{} [@user]".format(_name.capitalize(), PREFIX, _name))


# ==========================================================================
# 2) MODERATION  (35)  -- uses the permissions of the logged-in account
# ==========================================================================
async def _purge(ctx, limit, check=None):
    limit = max(1, min(limit, 500))
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    deleted = await ctx.channel.purge(limit=limit, check=check, bulk=False)
    await ctx.send("🧹 Deleted {} message(s).".format(len(deleted)), delete_after=5)


@command("Moderation", "kick")
@commands.guild_only()
@commands.has_permissions(kick_members=True)
async def c_kick(ctx, member: discord.Member, *, reason: str = "No reason given"):
    """Kick a member. Usage: kick <member> [reason]"""
    await member.kick(reason=reason)
    await say(ctx, "👢 Kicked **{}**. Reason: {}".format(member, reason))


@command("Moderation", "ban")
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def c_ban(ctx, member: discord.Member, *, reason: str = "No reason given"):
    """Ban a member. Usage: ban <member> [reason]"""
    await member.ban(reason=reason)
    await say(ctx, "🔨 Banned **{}**. Reason: {}".format(member, reason))


@command("Moderation", "unban")
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def c_unban(ctx, user: discord.User, *, reason: str = "No reason given"):
    """Unban a user by ID. Usage: unban <user_id>"""
    await ctx.guild.unban(user, reason=reason)
    await say(ctx, "✅ Unbanned **{}**.".format(user))


@command("Moderation", "softban")
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def c_softban(ctx, member: discord.Member, *, reason: str = "Softban"):
    """Ban then immediately unban to clear recent messages."""
    try:
        await member.ban(reason=reason, delete_message_seconds=86400)
    except TypeError:
        await member.ban(reason=reason, delete_message_days=1)
    await ctx.guild.unban(member, reason="Softban complete")
    await say(ctx, "🧽 Softbanned **{}**.".format(member))


@command("Moderation", "timeout")
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def c_timeout(ctx, member: discord.Member, minutes: int = 10, *, reason: str = "No reason given"):
    """Timeout a member. Usage: timeout <member> [minutes] [reason]"""
    minutes = max(1, min(minutes, 40320))
    await member.timeout(timedelta(minutes=minutes), reason=reason)
    await say(ctx, "🤐 Timed out **{}** for {} minute(s).".format(member, minutes))


@command("Moderation", "untimeout")
@commands.guild_only()
@commands.has_permissions(moderate_members=True)
async def c_untimeout(ctx, member: discord.Member):
    """Remove a member's timeout."""
    await member.timeout(None)
    await say(ctx, "🔊 Removed timeout from **{}**.".format(member))


@command("Moderation", "purge")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def c_purge(ctx, amount: int = 10):
    """Delete the last N messages. Usage: purge [amount]"""
    await _purge(ctx, amount)


@command("Moderation", "purgeme")
async def c_purgeme(ctx, amount: int = 10):
    """Delete your own last N messages."""
    await _purge(ctx, amount * 5, lambda m: m.author.id == bot.user.id)


@command("Moderation", "purgeuser")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def c_purgeuser(ctx, member: discord.Member, amount: int = 20):
    """Delete a member's recent messages."""
    await _purge(ctx, amount, lambda m: m.author.id == member.id)


@command("Moderation", "purgebots")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def c_purgebots(ctx, amount: int = 50):
    """Delete recent messages sent by bots."""
    await _purge(ctx, amount, lambda m: m.author.bot)


@command("Moderation", "purgecontains")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def c_purgecontains(ctx, *, text: str):
    """Delete recent messages containing some text (searches last 100)."""
    needle = text.lower()
    await _purge(ctx, 100, lambda m: needle in m.content.lower())


@command("Moderation", "purgelinks")
@commands.guild_only()
@commands.has_permissions(manage_messages=True)
async def c_purgelinks(ctx, amount: int = 50):
    """Delete recent messages containing links."""
    await _purge(ctx, amount, lambda m: re.search(r"https?://", m.content) is not None)


@command("Moderation", "slowmode")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_slowmode(ctx, seconds: int = 0):
    """Set channel slowmode (0 disables)."""
    await ctx.channel.edit(slowmode_delay=max(0, min(seconds, 21600)))
    await say(ctx, "🐌 Slowmode set to {}s.".format(seconds))


@command("Moderation", "lock")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_lock(ctx):
    """Stop @everyone from sending messages in this channel."""
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = False
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await say(ctx, "🔒 Channel locked.")


@command("Moderation", "unlock")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_unlock(ctx):
    """Undo lock."""
    overwrite = ctx.channel.overwrites_for(ctx.guild.default_role)
    overwrite.send_messages = None
    await ctx.channel.set_permissions(ctx.guild.default_role, overwrite=overwrite)
    await say(ctx, "🔓 Channel unlocked.")


@command("Moderation", "nick")
@commands.guild_only()
@commands.has_permissions(manage_nicknames=True)
async def c_nick(ctx, member: discord.Member, *, nickname: str):
    """Change a member's nickname."""
    await member.edit(nick=nickname[:32])
    await say(ctx, "✏️ Nickname updated.")


@command("Moderation", "resetnick")
@commands.guild_only()
@commands.has_permissions(manage_nicknames=True)
async def c_resetnick(ctx, member: discord.Member):
    """Reset a member's nickname."""
    await member.edit(nick=None)
    await say(ctx, "♻️ Nickname reset.")


@command("Moderation", "roleadd")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def c_roleadd(ctx, member: discord.Member, *, role: discord.Role):
    """Give a role to a member."""
    await member.add_roles(role)
    await say(ctx, "➕ Gave **{}** to **{}**.".format(role.name, member))


@command("Moderation", "roleremove")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def c_roleremove(ctx, member: discord.Member, *, role: discord.Role):
    """Remove a role from a member."""
    await member.remove_roles(role)
    await say(ctx, "➖ Removed **{}** from **{}**.".format(role.name, member))


@command("Moderation", "rolecreate")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def c_rolecreate(ctx, *, name: str):
    """Create a role."""
    role = await ctx.guild.create_role(name=name[:100])
    await say(ctx, "🆕 Created role **{}** (`{}`).".format(role.name, role.id))


@command("Moderation", "roledelete")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def c_roledelete(ctx, *, role: discord.Role):
    """Delete a role."""
    await role.delete()
    await say(ctx, "🗑️ Deleted role **{}**.".format(role.name))


@command("Moderation", "rolecolor")
@commands.guild_only()
@commands.has_permissions(manage_roles=True)
async def c_rolecolor(ctx, hex_color: str, *, role: discord.Role):
    """Set a role colour. Usage: rolecolor #ff8800 <role>"""
    await role.edit(colour=discord.Colour(int(hex_color.lstrip("#"), 16)))
    await say(ctx, "🎨 Updated colour of **{}**.".format(role.name))


@command("Moderation", "topic")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_topic(ctx, *, text: str):
    """Set the channel topic."""
    await ctx.channel.edit(topic=text[:1024])
    await say(ctx, "📝 Topic updated.")


@command("Moderation", "channelrename")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_channelrename(ctx, *, name: str):
    """Rename this channel."""
    await ctx.channel.edit(name=name[:100])
    await say(ctx, "✏️ Channel renamed.")


@command("Moderation", "channelcreate")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_channelcreate(ctx, *, name: str):
    """Create a text channel."""
    channel = await ctx.guild.create_text_channel(name[:100])
    await say(ctx, "🆕 Created {} (`{}`).".format(channel.name, channel.id))


@command("Moderation", "channeldelete")
@commands.guild_only()
@commands.has_permissions(manage_channels=True)
async def c_channeldelete(ctx, channel: discord.abc.GuildChannel):
    """Delete a channel (you must name it explicitly)."""
    name = channel.name
    await channel.delete()
    if channel.id != ctx.channel.id:
        await say(ctx, "🗑️ Deleted channel **{}**.".format(name))


@command("Moderation", "warn")
@commands.guild_only()
async def c_warn(ctx, member: discord.Member, *, reason: str = "No reason given"):
    """Record a warning locally (stored in the data file)."""
    warns = DB.setdefault("warns", {}).setdefault(str(ctx.guild.id), {}).setdefault(str(member.id), [])
    warns.append({"reason": reason, "time": int(time.time())})
    save_data()
    await say(ctx, "⚠️ Warned **{}** ({} total). Reason: {}".format(member, len(warns), reason))


@command("Moderation", "warns")
@commands.guild_only()
async def c_warns(ctx, member: discord.Member):
    """List stored warnings for a member."""
    warns = DB.get("warns", {}).get(str(ctx.guild.id), {}).get(str(member.id), [])
    if not warns:
        return await say(ctx, "✅ No warnings for **{}**.".format(member))
    lines = ["{}. {} (<t:{}:R>)".format(i, w["reason"], w["time"]) for i, w in enumerate(warns, 1)]
    await say(ctx, "**Warnings for {}**\n{}".format(member, "\n".join(lines)))


@command("Moderation", "clearwarns")
@commands.guild_only()
async def c_clearwarns(ctx, member: discord.Member):
    """Clear stored warnings for a member."""
    DB.get("warns", {}).get(str(ctx.guild.id), {}).pop(str(member.id), None)
    save_data()
    await say(ctx, "🧼 Cleared warnings for **{}**.".format(member))


@command("Moderation", "banlist")
@commands.guild_only()
@commands.has_permissions(ban_members=True)
async def c_banlist(ctx):
    """Show up to 25 banned users."""
    lines = []
    async for entry in ctx.guild.bans(limit=25):
        lines.append("{} (`{}`)".format(entry.user, entry.user.id))
    await say(ctx, "🚫 **Bans**\n" + ("\n".join(lines) or "No bans."))


@command("Moderation", "vmute")
@commands.guild_only()
@commands.has_permissions(mute_members=True)
async def c_vmute(ctx, member: discord.Member):
    """Server-mute a member in voice."""
    await member.edit(mute=True)
    await say(ctx, "🔇 Voice-muted **{}**.".format(member))


@command("Moderation", "vunmute")
@commands.guild_only()
@commands.has_permissions(mute_members=True)
async def c_vunmute(ctx, member: discord.Member):
    """Remove a voice server-mute."""
    await member.edit(mute=False)
    await say(ctx, "🔈 Voice-unmuted **{}**.".format(member))


@command("Moderation", "vkick")
@commands.guild_only()
@commands.has_permissions(move_members=True)
async def c_vkick(ctx, member: discord.Member):
    """Disconnect a member from voice."""
    await member.move_to(None)
    await say(ctx, "📴 Disconnected **{}** from voice.".format(member))


@command("Moderation", "pin")
@commands.guild_only()
async def c_pin(ctx):
    """Pin the message you reply to."""
    ref = get_ref(ctx)
    if not ref:
        return await say(ctx, "⚠️ Reply to the message you want to pin.")
    await ref.pin()
    await say(ctx, "📌 Pinned.")


@command("Moderation", "unpin")
@commands.guild_only()
async def c_unpin(ctx):
    """Unpin the message you reply to."""
    ref = get_ref(ctx)
    if not ref:
        return await say(ctx, "⚠️ Reply to the message you want to unpin.")
    await ref.unpin()
    await say(ctx, "📍 Unpinned.")


# ==========================================================================
# 3) FUN  (40)
# ==========================================================================
JOKES = [
    "Why don't scientists trust atoms? They make up everything.",
    "I told my computer I needed a break. It went to sleep.",
    "Why did the developer go broke? He used up all his cache.",
    "I'd tell you a UDP joke, but you might not get it.",
    "Parallel lines have so much in common. It's a shame they'll never meet.",
    "Why do programmers prefer dark mode? Light attracts bugs.",
]
DAD_JOKES = [
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "I used to hate facial hair, but then it grew on me.",
    "What do you call fake spaghetti? An impasta.",
    "Did you hear about the restaurant on the moon? Great food, no atmosphere.",
    "I only know 25 letters of the alphabet. I don't know y.",
    "Why did the scarecrow win an award? He was outstanding in his field.",
]
FACTS = [
    "Honey never spoils; edible honey has been found in ancient Egyptian tombs.",
    "Octopuses have three hearts and blue blood.",
    "Bananas are berries, but strawberries are not.",
    "A day on Venus is longer than a year on Venus.",
    "Sweden has more islands than any other country.",
    "Wombat droppings are cube-shaped.",
]
INSPIRE = [
    "A journey of a thousand miles begins with a single step.",
    "Well done is better than well said.",
    "Fall seven times, stand up eight.",
    "The best time to plant a tree was 20 years ago. The second best time is now.",
    "Small steps every day add up to big results.",
    "Done is better than perfect.",
]
ADVICE = [
    "Drink some water.",
    "Back up your files before you 'quickly fix' something.",
    "Sleep on big decisions.",
    "Read the error message twice.",
    "Take a short walk; the bug will still be there.",
    "Commit early, commit often.",
]
RIDDLES = [
    ("What has keys but can't open locks?", "A keyboard"),
    ("What gets wetter the more it dries?", "A towel"),
    ("What has hands but can't clap?", "A clock"),
    ("What can travel the world while staying in a corner?", "A stamp"),
    ("The more you take, the more you leave behind. What am I?", "Footsteps"),
]
TRUTHS = [
    "What's the most embarrassing song on your playlist?",
    "What's a skill you pretend to have?",
    "What's the weirdest thing you've googled this week?",
    "What's your most irrational fear?",
    "Which app do you waste the most time on?",
]
DARES = [
    "Send the last emoji you used five times in a row.",
    "Change your nickname to 'Potato' for an hour.",
    "Type the next message with your elbows.",
    "Write a two-line poem about your keyboard.",
    "Talk like a pirate for the next 10 minutes.",
]
WYR = [
    "Would you rather always be 10 minutes late or 20 minutes early?",
    "Would you rather have unlimited pizza or unlimited tacos?",
    "Would you rather fight one horse-sized duck or 100 duck-sized horses?",
    "Would you rather lose your phone or lose your wallet?",
    "Would you rather never use social media again or never watch videos again?",
]
NHIE = [
    "Never have I ever stayed up all night gaming.",
    "Never have I ever sent a message to the wrong chat.",
    "Never have I ever fallen asleep in a call.",
    "Never have I ever pretended my mic was broken.",
    "Never have I ever Googled my own name.",
]
ROASTS = [
    "You're the human version of a loading screen.",
    "Your Wi-Fi has better connections than you do.",
    "You bring everyone so much joy... when you leave the call.",
    "You're like a software update: nobody asked, and it takes forever.",
    "If procrastination were a sport, you'd still show up late to the final.",
]
COMPLIMENTS = [
    "You have a great sense of humor.",
    "You make hard things look easy.",
    "Your curiosity is contagious.",
    "You're someone people are glad to see in chat.",
    "You always bring good energy.",
]
FORTUNES = [
    "A pleasant surprise is waiting for you.",
    "Today's bug is tomorrow's feature.",
    "Good things come to those who refactor.",
    "An old friend will message you soon.",
    "Your next idea will be a great one.",
]
PICKUP = [
    "Are you a keyboard? Because you're just my type.",
    "Are you a compiler? Because you make my heart skip errors.",
    "Do you have a map? I keep getting lost in your profile picture.",
    "Is your name Wi-Fi? Because I'm feeling a connection.",
]
SHOWER = [
    "If you clean a vacuum cleaner, you become the vacuum cleaner.",
    "Your future self is watching you right now through memories.",
    "The word 'bed' looks like a bed.",
    "Every 'password' you set is a tiny act of trust in your own memory.",
    "Cereal is just breakfast soup you eat with a spoon.",
]
CONCH = ["Maybe someday.", "Nothing.", "Neither.", "Follow the seahorse.", "I don't think so.", "Yes.", "Try asking again."]
ANIMALS = ["🐶 Dog", "🐱 Cat", "🦊 Fox", "🐼 Panda", "🐨 Koala", "🦉 Owl", "🐧 Penguin", "🦦 Otter", "🐢 Turtle", "🦔 Hedgehog"]
EMOJIS = list("😀😎🤖🔥🌈🍕🎮🚀🧠🦄🍀🎲🛸🪐🥳🤯😴🧃🌮🎧")
BALL = [
    "It is certain.", "Without a doubt.", "You may rely on it.", "Yes, definitely.", "Most likely.",
    "Reply hazy, try again.", "Ask again later.", "Cannot predict now.", "Don't count on it.",
    "My reply is no.", "Very doubtful.", "Outlook not so good.",
]


def make_list_cmd(items, template="{}"):
    async def callback(ctx):
        await say(ctx, template.format(random.choice(items)))
    return callback


for _name, _items, _tpl in (
    ("joke", JOKES, "😂 {}"), ("dadjoke", DAD_JOKES, "👨 {}"), ("fact", FACTS, "📚 {}"),
    ("inspire", INSPIRE, "💡 {}"), ("advice", ADVICE, "🧭 {}"), ("truth", TRUTHS, "🫣 Truth: {}"),
    ("dare", DARES, "😈 Dare: {}"), ("wyr", WYR, "🤔 {}"), ("nhie", NHIE, "🙊 {}"),
    ("roast", ROASTS, "🔥 {}"), ("compliment", COMPLIMENTS, "💖 {}"), ("fortune", FORTUNES, "🥠 {}"),
    ("pickup", PICKUP, "😏 {}"), ("shower", SHOWER, "🚿 {}"), ("conch", CONCH, "🐚 The Magic Conch says: {}"),
    ("animal", ANIMALS, "Your spirit animal is {}!"), ("emoji", EMOJIS, "{}"),
):
    register("Fun", _name, make_list_cmd(_items, _tpl), "Random {}. Usage: {}{}".format(_name, PREFIX, _name))


async def _riddle(ctx):
    q, a = random.choice(RIDDLES)
    await say(ctx, "🧩 {}\nAnswer: ||{}||".format(q, a))


register("Fun", "riddle", _riddle, "Get a riddle (answer is spoilered).")


def make_static(text):
    async def callback(ctx):
        await say(ctx, text)
    return callback


for _name, _text in (("lenny", "( ͡° ͜ʖ ͡°)"), ("shruggie", "¯\\_(ツ)_/¯"), ("tableflip", "(╯°□°）╯︵ ┻━┻"),
                     ("unflip", "┬─┬ ノ( ゜-゜ノ)"), ("sus", "ඞ  You are looking a little sus...")):
    register("Fun", _name, make_static(_text), "Send {}.".format(_name))


def make_rating(label, emoji, hundred=True):
    async def callback(ctx, *, what: str = ""):
        subject = what.strip() or ctx.author.display_name
        value = random.randint(0, 100)
        await say(ctx, "{} **{}**'s {}: **{}%**".format(emoji, subject, label, value))
    return callback


for _name, _label, _emoji in (("rate", "rating", "⭐"), ("vibecheck", "vibe", "🌊"),
                              ("luck", "luck today", "🍀"), ("rizz", "rizz level", "😎")):
    register("Fun", _name, make_rating(_label, _emoji), "Rate someone/something. Usage: {}{} [thing]".format(PREFIX, _name))


@command("Fun", "8ball")
async def c_8ball(ctx, *, question: str = ""):
    """Ask the magic 8-ball."""
    await say(ctx, "🎱 {}".format(random.choice(BALL)))


@command("Fun", "coinflip")
async def c_coinflip(ctx):
    """Flip a coin."""
    await say(ctx, "🪙 {}!".format(random.choice(["Heads", "Tails"])))


@command("Fun", "coinstreak")
async def c_coinstreak(ctx, count: int = 10):
    """Flip N coins (max 100)."""
    flips = [random.choice("HT") for _ in range(max(1, min(count, 100)))]
    await say(ctx, "🪙 {}\nHeads: {} | Tails: {}".format("".join(flips), flips.count("H"), flips.count("T")))


@command("Fun", "dice")
async def c_dice(ctx, notation: str = "1d6"):
    """Roll dice in NdM notation. Usage: dice 2d20"""
    match = re.fullmatch(r"(\d{1,3})d(\d{1,4})", notation.lower())
    if not match:
        return await say(ctx, "⚠️ Use NdM, e.g. `2d6`.")
    n, m = int(match[1]), int(match[2])
    if n < 1 or m < 2:
        return await say(ctx, "⚠️ Need at least 1 die with 2 sides.")
    rolls = [random.randint(1, m) for _ in range(n)]
    await say(ctx, "🎲 {} → {} = **{}**".format(notation, rolls if n <= 20 else "...", sum(rolls)))


@command("Fun", "choose")
async def c_choose(ctx, *, options: str):
    """Pick one option. Separate with | or commas."""
    parts = [p.strip() for p in re.split(r"[|,]", options) if p.strip()]
    if len(parts) < 2:
        return await say(ctx, "⚠️ Give at least two options separated by `|` or `,`.")
    await say(ctx, "🤔 I choose: **{}**".format(random.choice(parts)))


@command("Fun", "ship")
async def c_ship(ctx, first: str, *, second: str):
    """Ship two names (same pair always gives the same result)."""
    pair = "|".join(sorted([first.lower(), second.lower()]))
    pct = int(hashlib.md5(pair.encode()).hexdigest(), 16) % 101
    bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
    await say(ctx, "💞 {} × {}\n`{}` **{}%**".format(first, second, bar, pct))


@command("Fun", "rps")
async def c_rps(ctx, choice: str):
    """Rock paper scissors. Usage: rps rock|paper|scissors"""
    choice = choice.lower()
    options = ["rock", "paper", "scissors"]
    if choice not in options:
        return await say(ctx, "⚠️ Choose rock, paper or scissors.")
    bot_choice = random.choice(options)
    beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
    result = "It's a tie!" if choice == bot_choice else ("You win! 🎉" if beats[choice] == bot_choice else "I win! 😎")
    await say(ctx, "You: **{}** | Me: **{}** → {}".format(choice, bot_choice, result))


@command("Fun", "slots")
async def c_slots(ctx):
    """Spin the slot machine."""
    reels = [random.choice("🍒🍋🔔💎7️⃣") for _ in range(3)]
    verdict = "JACKPOT! 🎉" if len(set(reels)) == 1 else ("Nice, a pair!" if len(set(reels)) == 2 else "No luck.")
    await say(ctx, "🎰 | {} | — {}".format(" ".join(reels), verdict))


@command("Fun", "russianroulette")
async def c_russianroulette(ctx):
    """Pull the trigger (1 in 6, harmless)."""
    await say(ctx, "💥 BANG! (you're fine, it's a joke)" if random.randint(1, 6) == 1 else "🔫 *click*")


@command("Fun", "lottery")
async def c_lottery(ctx):
    """Draw six lottery numbers."""
    await say(ctx, "🎟️ {}".format(" - ".join(str(n) for n in sorted(random.sample(range(1, 50), 6)))))


@command("Fun", "yesno")
async def c_yesno(ctx, *, question: str = ""):
    """Get a yes/no/maybe answer."""
    await say(ctx, random.choice(["✅ Yes", "❌ No", "🤷 Maybe"]))


@command("Fun", "horoscope")
async def c_horoscope(ctx, sign: str = "aries"):
    """Daily horoscope (stable for the day)."""
    rng = random.Random("{}{}".format(sign.lower(), datetime.utcnow().date()))
    await say(ctx, "🔮 **{}**: {} Lucky number: {}.".format(sign.title(), rng.choice(FORTUNES), rng.randint(1, 99)))


@command("Fun", "mood")
async def c_mood(ctx):
    """Get a random mood."""
    await say(ctx, "Today's mood: {}".format(random.choice(["😄 Energetic", "😌 Calm", "🤪 Chaotic", "😴 Sleepy", "🧐 Focused", "🥳 Festive"])))


# ==========================================================================
# 4) TEXT  (40)  -- every command also works on the message you reply to
# ==========================================================================
MORSE = {
    "a": ".-", "b": "-...", "c": "-.-.", "d": "-..", "e": ".", "f": "..-.", "g": "--.", "h": "....",
    "i": "..", "j": ".---", "k": "-.-", "l": ".-..", "m": "--", "n": "-.", "o": "---", "p": ".--.",
    "q": "--.-", "r": ".-.", "s": "...", "t": "-", "u": "..-", "v": "...-", "w": ".--", "x": "-..-",
    "y": "-.--", "z": "--..", "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
}
UNMORSE = {v: k for k, v in MORSE.items()}
UPSIDE = dict(zip("abcdefghijklmnopqrstuvwxyz", "ɐqɔpǝɟƃɥᴉɾʞlɯuodbɹsʇnʌʍxʎz"))
UPSIDE.update({"?": "¿", "!": "¡", ".": "˙", ",": "'"})
NUMWORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]


def t_emojify(t):
    out = []
    for c in t.lower():
        if "a" <= c <= "z":
            out.append(":regional_indicator_{}:".format(c))
        elif c.isdigit():
            out.append(":{}:".format(NUMWORDS[int(c)]))
        else:
            out.append("   " if c == " " else c)
    return " ".join(out)


def t_caesar(t):
    first, _, rest = t.partition(" ")
    try:
        shift = int(first)
    except ValueError:
        shift, rest = 3, t

    def move(c):
        if c.isascii() and c.isalpha():
            base = ord("A") if c.isupper() else ord("a")
            return chr((ord(c) - base + shift) % 26 + base)
        return c
    return "".join(move(c) for c in rest)


def t_atbash(t):
    def flip(c):
        if c.isascii() and c.isalpha():
            base = ord("A") if c.isupper() else ord("a")
            return chr(base + 25 - (ord(c) - base))
        return c
    return "".join(flip(c) for c in t)


def t_repeat(t):
    first, _, rest = t.partition(" ")
    if first.isdigit() and rest:
        return " ".join([rest] * min(int(first), 20))
    return " ".join([t] * 3)


def t_words(t):
    return re.findall(r"[A-Za-z0-9]+", t)


TEXT_FUNCS = [
    ("upper", "UPPERCASE text.", lambda t: t.upper()),
    ("lower", "lowercase text.", lambda t: t.lower()),
    ("title", "Title Case text.", lambda t: t.title()),
    ("swapcase", "sWAP cASE.", lambda t: t.swapcase()),
    ("capitalize", "Capitalize the first letter.", lambda t: t.capitalize()),
    ("reverse", "Reverse the text.", lambda t: t[::-1]),
    ("reversewords", "Reverse word order.", lambda t: " ".join(t.split()[::-1])),
    ("mock", "mOcK tExT.", lambda t: "".join(c.upper() if i % 2 else c.lower() for i, c in enumerate(t))),
    ("uwu", "UwU-ify text.", lambda t: re.sub(r"n([aeiou])", r"ny\1", re.sub(r"[RL]", "W", re.sub(r"[rl]", "w", t))) + " uwu"),
    ("clapify", "Add 👏 between 👏 words.", lambda t: " 👏 ".join(t.split())),
    ("vaporwave", "ＶＡＰＯＲＷＡＶＥ text.", lambda t: "".join(chr(ord(c) + 0xFEE0) if "!" <= c <= "~" else c for c in t)),
    ("leet", "1337 5p34k.", lambda t: t.translate(str.maketrans("aeiostAEIOST", "431057431057"))),
    ("emojify", "Turn text into regional indicator emoji.", t_emojify),
    ("spoiler", "Spoiler every character.", lambda t: "".join("||{}||".format(c) for c in t[:300])),
    ("shout", "SHOUT!!!", lambda t: "**{}!!!**".format(t.upper())),
    ("zalgo", "Z̸a̵l̷g̶o̴ text.", lambda t: "".join(c + "".join(chr(random.randint(0x300, 0x36F)) for _ in range(random.randint(1, 4))) for c in t[:100])),
    ("flip", "Upside-down text.", lambda t: "".join(UPSIDE.get(c, c) for c in t.lower()[::-1])),
    ("morse", "Text to Morse code.", lambda t: " / ".join(" ".join(MORSE.get(c, "?") for c in w) for w in t.lower().split())),
    ("unmorse", "Morse code to text (use / between words).", lambda t: " ".join("".join(UNMORSE.get(code, "?") for code in w.split()) for w in t.split("/"))),
    ("binary", "Text to binary.", lambda t: " ".join(format(b, "08b") for b in t.encode())),
    ("unbinary", "Binary to text.", lambda t: bytes(int(b, 2) for b in t.split()).decode()),
    ("hex", "Text to hex.", lambda t: t.encode().hex()),
    ("unhex", "Hex to text.", lambda t: bytes.fromhex(t.replace(" ", "")).decode()),
    ("base64", "Encode as Base64.", lambda t: base64.b64encode(t.encode()).decode()),
    ("unbase64", "Decode Base64.", lambda t: base64.b64decode(t.encode()).decode()),
    ("rot13", "ROT13 cipher.", lambda t: codecs.encode(t, "rot13")),
    ("caesar", "Caesar cipher. Usage: caesar <shift> <text>", t_caesar),
    ("atbash", "Atbash cipher.", t_atbash),
    ("charcount", "Count characters.", lambda t: "{} characters ({} without spaces)".format(len(t), len(t.replace(" ", "")))),
    ("wordcount", "Count words.", lambda t: "{} words".format(len(t.split()))),
    ("sortwords", "Sort words alphabetically.", lambda t: " ".join(sorted(t.split(), key=str.lower))),
    ("uniqwords", "Remove duplicate words.", lambda t: " ".join(dict.fromkeys(t.split()))),
    ("palindrome", "Check for a palindrome.", lambda t: "✅ Yes" if re.sub(r"\W", "", t.lower()) == re.sub(r"\W", "", t.lower())[::-1] else "❌ No"),
    ("vowels", "Count vowels.", lambda t: "{} vowels".format(sum(c in "aeiouAEIOU" for c in t))),
    ("slugify", "make-a-url-slug.", lambda t: re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")),
    ("snake", "snake_case.", lambda t: "_".join(w.lower() for w in t_words(t))),
    ("camel", "camelCase.", lambda t: "".join(w.lower() if i == 0 else w.title() for i, w in enumerate(t_words(t)))),
    ("kebab", "kebab-case.", lambda t: "-".join(w.lower() for w in t_words(t))),
    ("acronym", "Make an ACRONYM.", lambda t: "".join(w[0].upper() for w in t.split())),
    ("repeat", "Repeat text. Usage: repeat <times> <text>", t_repeat),
]


def make_text_cmd(fn):
    async def callback(ctx, *, text: str = ""):
        text = get_text(ctx, text)
        if not text:
            return await say(ctx, "⚠️ Give me some text (or reply to a message). Usage: `{}{} <text>`".format(PREFIX, ctx.invoked_with))
        try:
            result = fn(text)
        except Exception as exc:  # noqa: BLE001 - friendly error for bad input
            return await say(ctx, "❌ {}: {}".format(type(exc).__name__, exc))
        await say(ctx, result)
    return callback


for _name, _help, _fn in TEXT_FUNCS:
    register("Text", _name, make_text_cmd(_fn), _help)


# ==========================================================================
# 5) MATH  (35)
# ==========================================================================
_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCS = {n: getattr(math, n) for n in (
    "sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "log2", "exp",
    "floor", "ceil", "radians", "degrees")}
_FUNCS.update({"abs": abs, "round": round, "min": min, "max": max})
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def safe_eval(expr):
    """Evaluate an arithmetic expression without using eval()."""
    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
            left, right = ev(node.left), ev(node.right)
            if isinstance(node.op, ast.Pow):
                if abs(right) > 1000 or (isinstance(left, int) and left.bit_length() * abs(right) > 20000):
                    raise ValueError("result too large")
            return _OPS[type(node.op)](left, right)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
            return _OPS[type(node.op)](ev(node.operand))
        if isinstance(node, ast.Name) and node.id in _CONSTS:
            return _CONSTS[node.id]
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id in _FUNCS and not node.keywords):
            return _FUNCS[node.func.id](*[ev(a) for a in node.args])
        raise ValueError("unsupported expression")
    return ev(ast.parse(expr.replace("^", "**").strip(), mode="eval"))


@command("Math", "calc")
async def c_calc(ctx, *, expression: str):
    """Evaluate math safely. Supports + - * / // % ^, sqrt, sin, log, pi, e..."""
    try:
        result = safe_eval(expression)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError, TypeError) as exc:
        return await say(ctx, "❌ {}".format(exc or "could not evaluate"))
    await say(ctx, "🧮 `{}` = **{}**".format(expression.strip(), fmt_num(result)))


def _bounded(x, low, high):
    n = to_int(x)
    if not low <= n <= high:
        raise ValueError("value must be between {} and {}".format(low, high))
    return n


def _safe_pow(a, b):
    if abs(b) > 1000:
        raise ValueError("exponent too large")
    return a ** b


def _fib(n):
    n = _bounded(n, 0, 5000)
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def _is_prime(n):
    n = _bounded(n, -10 ** 12, 10 ** 12)
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True


def _next_prime(n):
    n = _bounded(n, -10 ** 12, 10 ** 12) + 1
    while not _is_prime(n):
        n += 1
    return n


def _lcm(a, b):
    return a * b // math.gcd(a, b) if a and b else 0


MATH_FUNCS = [
    ("sqrt", "Square root.", lambda a, t: math.sqrt(a[0]), ""),
    ("cbrt", "Cube root.", lambda a, t: math.copysign(abs(a[0]) ** (1 / 3), a[0]), ""),
    ("pow", "Power: pow <base> <exp>.", lambda a, t: _safe_pow(a[0], a[1]), ""),
    ("factorial", "Factorial (n <= 2000).", lambda a, t: math.factorial(_bounded(a[0], 0, 2000)), ""),
    ("fib", "Nth Fibonacci number.", lambda a, t: _fib(a[0]), ""),
    ("isprime", "Is the number prime?", lambda a, t: "✅ Prime" if _is_prime(a[0]) else "❌ Not prime", ""),
    ("nextprime", "Next prime after N.", lambda a, t: _next_prime(a[0]), ""),
    ("gcd", "Greatest common divisor.", lambda a, t: functools.reduce(math.gcd, [to_int(x) for x in a]), ""),
    ("lcm", "Least common multiple.", lambda a, t: functools.reduce(_lcm, [to_int(x) for x in a]), ""),
    ("abs", "Absolute value.", lambda a, t: abs(a[0]), ""),
    ("round", "Round: round <number> [digits].", lambda a, t: round(a[0], int(a[1]) if len(a) > 1 else 0), ""),
    ("percent", "X percent of Y: percent <x> <y>.", lambda a, t: a[0] / 100 * a[1], ""),
    ("avg", "Average of numbers.", lambda a, t: statistics.mean(a), ""),
    ("sum", "Sum of numbers.", lambda a, t: sum(a), ""),
    ("min", "Smallest number.", lambda a, t: min(a), ""),
    ("max", "Largest number.", lambda a, t: max(a), ""),
    ("median", "Median of numbers.", lambda a, t: statistics.median(a), ""),
    ("stdev", "Standard deviation.", lambda a, t: statistics.stdev(a), ""),
    ("tobin", "Decimal to binary.", lambda a, t: format(to_int(a[0]), "b"), ""),
    ("tohex", "Decimal to hex.", lambda a, t: format(to_int(a[0]), "x"), ""),
    ("tooct", "Decimal to octal.", lambda a, t: format(to_int(a[0]), "o"), ""),
    ("frombin", "Binary to decimal.", lambda a, t: int(t.replace(" ", ""), 2), ""),
    ("fromhex", "Hex to decimal.", lambda a, t: int(t.replace(" ", ""), 16), ""),
    ("fromoct", "Octal to decimal.", lambda a, t: int(t.replace(" ", ""), 8), ""),
    ("c2f", "Celsius to Fahrenheit.", lambda a, t: a[0] * 9 / 5 + 32, "°F"),
    ("f2c", "Fahrenheit to Celsius.", lambda a, t: (a[0] - 32) * 5 / 9, "°C"),
    ("km2mi", "Kilometres to miles.", lambda a, t: a[0] * 0.621371, "mi"),
    ("mi2km", "Miles to kilometres.", lambda a, t: a[0] / 0.621371, "km"),
    ("kg2lb", "Kilograms to pounds.", lambda a, t: a[0] * 2.20462, "lb"),
    ("lb2kg", "Pounds to kilograms.", lambda a, t: a[0] / 2.20462, "kg"),
    ("m2ft", "Metres to feet.", lambda a, t: a[0] * 3.28084, "ft"),
    ("ft2m", "Feet to metres.", lambda a, t: a[0] / 3.28084, "m"),
    ("bmi", "BMI: bmi <kg> <cm>.", lambda a, t: round(a[0] / ((a[1] / 100) ** 2), 1), "(BMI)"),
    ("tip", "Tip: tip <bill> <percent>.", lambda a, t: "tip {:.2f}, total {:.2f}".format(a[0] * a[1] / 100, a[0] * (1 + a[1] / 100)), ""),
]


def make_math_cmd(fn, unit):
    async def callback(ctx, *, text: str = ""):
        nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", text)]
        try:
            result = fn(nums, text.strip())
        except (ValueError, ZeroDivisionError, IndexError, OverflowError, TypeError, statistics.StatisticsError) as exc:
            return await say(ctx, "❌ {} - check your arguments (`{}{} <numbers>`).".format(
                type(exc).__name__, PREFIX, ctx.invoked_with))
        await say(ctx, "🧮 **{}** {}".format(fmt_num(result), unit).strip())
    return callback


for _name, _help, _fn, _unit in MATH_FUNCS:
    register("Math", _name, make_math_cmd(_fn, _unit), _help)


# ==========================================================================
# 6) INFO  (35)
# ==========================================================================
@bot.listen("on_message_delete")
async def _snipe_delete(message):
    if message.content:
        SNIPES[message.channel.id] = (str(message.author), message.content, message.created_at)


@bot.listen("on_message_edit")
async def _snipe_edit(before, after):
    if before.content and before.content != after.content:
        EDIT_SNIPES[before.channel.id] = (str(before.author), before.content, after.content)


@command("Info", "ping")
async def c_ping(ctx):
    """Reply with the gateway latency."""
    await ctx.reply("🏓 Pong! `{}ms`".format(round(bot.latency * 1000)), mention_author=False)


@command("Info", "uptime")
async def c_uptime(ctx):
    """How long the script has been running."""
    await say(ctx, "⏱️ Up for **{}**".format(human_duration(time.time() - START_TIME)))


@command("Info", "stats")
async def c_stats(ctx):
    """Script statistics."""
    await say(ctx, "📊 Servers: {} | Commands: {} | Latency: {}ms | Uptime: {}".format(
        len(bot.guilds), len(bot.commands), round(bot.latency * 1000), human_duration(time.time() - START_TIME)))


@command("Info", "userinfo")
async def c_userinfo(ctx, user: Optional[discord.User] = None):
    """Show info about a user."""
    user = user or ctx.author
    lines = ["**{}** (`{}`)".format(user, user.id), "Created: " + fmt_dt(discord.utils.snowflake_time(user.id)),
             "Bot: {}".format("yes" if user.bot else "no")]
    member = ctx.guild.get_member(user.id) if ctx.guild else None
    if member and member.joined_at:
        lines.append("Joined: " + fmt_dt(member.joined_at))
        lines.append("Roles: {}".format(max(len(member.roles) - 1, 0)))
    await say(ctx, "\n".join(lines))


@command("Info", "serverinfo")
@commands.guild_only()
async def c_serverinfo(ctx):
    """Show info about this server."""
    g = ctx.guild
    await say(ctx, "**{}** (`{}`)\nMembers: {} | Channels: {} | Roles: {} | Emojis: {}\nBoosts: {} (tier {})\nCreated: {}".format(
        g.name, g.id, g.member_count, len(g.channels), len(g.roles), len(g.emojis),
        g.premium_subscription_count, g.premium_tier, fmt_dt(g.created_at)))


@command("Info", "avatar")
async def c_avatar(ctx, user: Optional[discord.User] = None):
    """Get a user's avatar URL."""
    user = user or ctx.author
    await say(ctx, user.display_avatar.url)


@command("Info", "banner")
async def c_banner(ctx, user: Optional[discord.User] = None):
    """Get a user's banner URL."""
    user = await bot.fetch_user((user or ctx.author).id)
    await say(ctx, user.banner.url if user.banner else "No banner set.")


@command("Info", "servericon")
@commands.guild_only()
async def c_servericon(ctx):
    """Get the server icon URL."""
    await say(ctx, ctx.guild.icon.url if ctx.guild.icon else "This server has no icon.")


@command("Info", "roleinfo")
@commands.guild_only()
async def c_roleinfo(ctx, *, role: discord.Role):
    """Show info about a role."""
    await say(ctx, "**{}** (`{}`)\nColour: {} | Position: {} | Members: {} | Mentionable: {}\nCreated: {}".format(
        role.name, role.id, role.colour, role.position, len(role.members), role.mentionable, fmt_dt(role.created_at)))


@command("Info", "channelinfo")
@commands.guild_only()
async def c_channelinfo(ctx, channel: Optional[discord.abc.GuildChannel] = None):
    """Show info about a channel."""
    channel = channel or ctx.channel
    await say(ctx, "**#{}** (`{}`)\nType: {}\nCreated: {}".format(
        channel.name, channel.id, channel.type, fmt_dt(channel.created_at)))


@command("Info", "roles")
@commands.guild_only()
async def c_roles(ctx):
    """List the server's roles."""
    names = [r.name for r in reversed(ctx.guild.roles) if r.name != "@everyone"]
    await say(ctx, "🎭 **{} roles**\n{}".format(len(names), ", ".join(names) or "none"))


@command("Info", "emojis")
@commands.guild_only()
async def c_emojis(ctx):
    """List the server's custom emojis."""
    emojis = ctx.guild.emojis
    await say(ctx, "😀 **{} emojis**\n{}".format(len(emojis), " ".join(str(e) for e in emojis[:30]) or "none"))


@command("Info", "membercount")
@commands.guild_only()
async def c_membercount(ctx):
    """Member count of this server."""
    await say(ctx, "👥 {} members".format(ctx.guild.member_count))


@command("Info", "boosts")
@commands.guild_only()
async def c_boosts(ctx):
    """Boost status of this server."""
    await say(ctx, "🚀 {} boosts (tier {})".format(ctx.guild.premium_subscription_count, ctx.guild.premium_tier))


@command("Info", "joined")
@commands.guild_only()
async def c_joined(ctx, member: Optional[discord.Member] = None):
    """When a member joined the server."""
    member = member or ctx.author
    await say(ctx, "📥 {} joined {}".format(member.display_name, fmt_dt(member.joined_at) if member.joined_at else "(unknown)"))


@command("Info", "created")
async def c_created(ctx, user: Optional[discord.User] = None):
    """When an account was created."""
    user = user or ctx.author
    await say(ctx, "🎂 {} was created {}".format(user, fmt_dt(discord.utils.snowflake_time(user.id))))


@command("Info", "snowflake")
async def c_snowflake(ctx, snowflake: int):
    """Convert a Discord ID into a timestamp."""
    await say(ctx, "❄️ " + fmt_dt(discord.utils.snowflake_time(snowflake)))


@command("Info", "id")
async def c_id(ctx):
    """Show your, the channel's and the server's IDs."""
    await say(ctx, "You: `{}`\nChannel: `{}`\nServer: `{}`".format(
        ctx.author.id, ctx.channel.id, ctx.guild.id if ctx.guild else "DM"))


@command("Info", "permissions")
@commands.guild_only()
async def c_permissions(ctx, member: Optional[discord.Member] = None):
    """List a member's permissions in this channel."""
    member = member or ctx.author
    granted = [name for name, value in ctx.channel.permissions_for(member) if value]
    await say(ctx, "🔑 **{}**\n{}".format(member.display_name, ", ".join(granted) or "none"))


@command("Info", "snipe")
async def c_snipe(ctx):
    """Show the last deleted message in this channel."""
    data = SNIPES.get(ctx.channel.id)
    await say(ctx, "🕵️ **{}**: {}".format(data[0], data[1]) if data else "Nothing to snipe.")


@command("Info", "editsnipe")
async def c_editsnipe(ctx):
    """Show the last edited message in this channel."""
    data = EDIT_SNIPES.get(ctx.channel.id)
    await say(ctx, "✏️ **{}**\nBefore: {}\nAfter: {}".format(*data) if data else "Nothing to snipe.")


@command("Info", "time")
async def c_time(ctx):
    """Current UTC time."""
    await say(ctx, "🕒 " + datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))


@command("Info", "date")
async def c_date(ctx):
    """Current UTC date."""
    await say(ctx, "📅 " + datetime.now(timezone.utc).strftime("%A, %Y-%m-%d"))


@command("Info", "timestamp")
async def c_timestamp(ctx, *, when: str = ""):
    """Discord timestamp for a date. Usage: timestamp 2026-12-24 18:00 (UTC)"""
    try:
        dt = parse_date(when).replace(tzinfo=timezone.utc) if when.strip() else datetime.now(timezone.utc)
    except ValueError as exc:
        return await say(ctx, "❌ {}".format(exc))
    ts = int(dt.timestamp())
    await say(ctx, "{}\n`<t:{}:F>` / `<t:{}:R>`".format(fmt_dt(dt), ts, ts))


@command("Info", "unix")
async def c_unix(ctx):
    """Current Unix timestamp."""
    await say(ctx, "🔢 {}".format(int(time.time())))


@command("Info", "cmds")
async def c_cmds(ctx):
    """How many commands are loaded."""
    await say(ctx, "📦 **{}** commands in **{}** categories.".format(len(bot.commands), len(REGISTRY)))


@command("Info", "categories")
async def c_categories(ctx):
    """List the command categories."""
    await say(ctx, "\n".join("**{}** - {} commands".format(c, len(n)) for c, n in REGISTRY.items()))


@command("Info", "help")
async def c_help(ctx, *, query: str = ""):
    """Show help. Usage: help [category|command]"""
    q = query.strip().lower().lstrip(PREFIX)
    if not q:
        body = "\n".join("**{}** ({}): `{}help {}`".format(c, len(n), PREFIX, c.lower()) for c, n in REGISTRY.items())
        return await say(ctx, "📖 **Categories**\n{}\n\nUse `{}help <command>` for details.".format(body, PREFIX))
    category = next((c for c in REGISTRY if c.lower() == q), None)
    if category:
        return await say(ctx, "**{}**\n{}".format(category, ", ".join("`{}`".format(n) for n in REGISTRY[category])))
    cmd = bot.get_command(q)
    if not cmd:
        return await say(ctx, "❓ Unknown command or category.")
    await say(ctx, "**{}{}** {}\n{}".format(PREFIX, cmd.name, cmd.signature, cmd.help or "No description."))


@command("Info", "cmdinfo")
async def c_cmdinfo(ctx, name: str):
    """Show category and usage of a command."""
    cmd = bot.get_command(name.lower())
    if not cmd:
        return await say(ctx, "❓ Unknown command.")
    await say(ctx, "`{}{} {}`\nCategory: {}\n{}".format(PREFIX, cmd.name, cmd.signature, CATEGORY_OF.get(cmd.name, "?"), cmd.help or ""))


@command("Info", "prefix")
async def c_prefix(ctx):
    """Show the current prefix."""
    await say(ctx, "The prefix is `{}`".format(PREFIX))


@command("Info", "version")
async def c_version(ctx):
    """Show the discord.py-self version."""
    await say(ctx, "discord.py-self `{}`".format(discord.__version__))


@command("Info", "python")
async def c_python(ctx):
    """Show the Python version."""
    await say(ctx, "🐍 Python `{}`".format(platform.python_version()))


@command("Info", "platform")
async def c_platform(ctx):
    """Show the OS platform."""
    await say(ctx, "💻 {} {}".format(platform.system(), platform.release()))


@command("Info", "channels")
@commands.guild_only()
async def c_channels(ctx):
    """Channel overview of this server."""
    g = ctx.guild
    await say(ctx, "📺 Text: {} | Voice: {} | Categories: {}".format(len(g.text_channels), len(g.voice_channels), len(g.categories)))


@command("Info", "whoami")
async def c_whoami(ctx):
    """Show the logged-in account."""
    u = bot.user
    await say(ctx, "🙋 **{}** (`{}`) - created {}".format(u, u.id, fmt_dt(discord.utils.snowflake_time(u.id))))


# ==========================================================================
# 7) UTILITY  (40)
# ==========================================================================
@command("Utility", "say")
async def c_say(ctx, *, text: str):
    """Send text and delete your command."""
    try:
        await ctx.message.delete()
    except discord.HTTPException:
        pass
    await ctx.send(discord.utils.escape_mentions(text))


async def _remind_later(ctx, seconds, text):
    await asyncio.sleep(seconds)
    await ctx.reply("⏰ {}".format(discord.utils.escape_mentions(text)), mention_author=False)


@command("Utility", "remind")
async def c_remind(ctx, when: str, *, text: str = "Time's up!"):
    """Remind yourself. Usage: remind 1h30m take a break (not kept after restart)"""
    seconds = parse_duration(when)
    if not 1 <= seconds <= 7 * 86400:
        return await say(ctx, "⚠️ Use a duration between 1s and 7d, e.g. `10m`, `1h30m`.")
    spawn(_remind_later(ctx, seconds, "Reminder: " + text))
    await say(ctx, "✅ I'll remind you in {}.".format(human_duration(seconds)))


@command("Utility", "timer")
async def c_timer(ctx, *, duration: str):
    """Start a timer. Usage: timer 90s"""
    seconds = parse_duration(duration)
    if not 1 <= seconds <= 86400:
        return await say(ctx, "⚠️ Use a duration between 1s and 24h.")
    spawn(_remind_later(ctx, seconds, "Timer finished ({})".format(human_duration(seconds))))
    await say(ctx, "⏲️ Timer set for {}.".format(human_duration(seconds)))


@command("Utility", "stopwatch")
async def c_stopwatch(ctx, action: str = "status"):
    """Stopwatch. Usage: stopwatch start|lap|stop|status"""
    action = action.lower()
    now = time.time()
    if action == "start":
        STOPWATCH.update(start=now, laps=[])
        return await say(ctx, "▶️ Stopwatch started.")
    if STOPWATCH["start"] is None:
        return await say(ctx, "⚠️ Start it first with `stopwatch start`.")
    elapsed = now - STOPWATCH["start"]
    if action == "lap":
        STOPWATCH["laps"].append(elapsed)
        return await say(ctx, "🏁 Lap {}: {:.2f}s".format(len(STOPWATCH["laps"]), elapsed))
    if action == "stop":
        STOPWATCH["start"] = None
        return await say(ctx, "⏹️ Stopped at {:.2f}s ({} laps).".format(elapsed, len(STOPWATCH["laps"])))
    await say(ctx, "⏱️ {:.2f}s elapsed.".format(elapsed))


def make_list_commands(section, add, show, remove, clear=None, label="item", link_reply=False):
    async def c_add(ctx, *, text: str = ""):
        ref = get_ref(ctx)
        text = get_text(ctx, text).strip()
        if not text:
            return await say(ctx, "⚠️ Give me something to save (or reply to a message).")
        if link_reply and ref:
            text = "{} {}".format(text[:100], ref.jump_url)
        DB.setdefault(section, []).append(text[:500])
        save_data()
        await say(ctx, "💾 Saved {} #{}.".format(label, len(DB[section])))

    async def c_show(ctx):
        items = DB.get(section, [])
        await say(ctx, "\n".join("{}. {}".format(i, t) for i, t in enumerate(items, 1)) or "Nothing saved yet.")

    async def c_remove(ctx, number: int):
        items = DB.get(section, [])
        if not 1 <= number <= len(items):
            return await say(ctx, "⚠️ No {} with that number.".format(label))
        removed = items.pop(number - 1)
        save_data()
        await say(ctx, "🗑️ Removed: {}".format(removed))

    register("Utility", add, c_add, "Save a {}. Usage: {}{} <text>".format(label, PREFIX, add))
    register("Utility", show, c_show, "List saved {}s.".format(label))
    register("Utility", remove, c_remove, "Remove a {} by number.".format(label))
    if clear:
        async def c_clear(ctx):
            DB[section] = []
            save_data()
            await say(ctx, "🧼 Cleared all {}s.".format(label))
        register("Utility", clear, c_clear, "Remove all saved {}s.".format(label))


make_list_commands("notes", "note", "notes", "delnote", "clearnotes", "note")
make_list_commands("todos", "todo", "todos", "tododone", "todoclear", "to-do")
make_list_commands("bookmarks", "bookmark", "bookmarks", "delbookmark", None, "bookmark", link_reply=True)


@command("Utility", "react")
async def c_react(ctx, *emojis: str):
    """React to the message you reply to. Usage: react 👍 🔥"""
    ref = get_ref(ctx)
    if not ref or not emojis:
        return await say(ctx, "⚠️ Reply to a message and give at least one emoji.")
    for emoji in emojis[:10]:
        await ref.add_reaction(emoji)


@command("Utility", "poll")
async def c_poll(ctx, *, poll: str):
    """Create a reaction poll. Usage: poll Question | option 1 | option 2"""
    parts = [p.strip() for p in poll.split("|") if p.strip()]
    if len(parts) < 3 or len(parts) > 10:
        return await say(ctx, "⚠️ Usage: `poll Question | option 1 | option 2` (2-9 options).")
    keycaps = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]
    body = "📊 **{}**\n{}".format(parts[0], "\n".join("{} {}".format(keycaps[i], o) for i, o in enumerate(parts[1:])))
    msg = await ctx.send(discord.utils.escape_mentions(body))
    for i in range(len(parts) - 1):
        await msg.add_reaction(keycaps[i])


@command("Utility", "typing")
async def c_typing(ctx, seconds: int = 5):
    """Show the typing indicator for N seconds (max 30)."""
    async with ctx.channel.typing():
        await asyncio.sleep(max(1, min(seconds, 30)))


@command("Utility", "setstatus")
async def c_setstatus(ctx, status: str):
    """Set presence: online, idle, dnd or invisible."""
    options = {"online": discord.Status.online, "idle": discord.Status.idle,
               "dnd": discord.Status.dnd, "invisible": discord.Status.invisible}
    if status.lower() not in options:
        return await say(ctx, "⚠️ Choose: online, idle, dnd, invisible.")
    await bot.change_presence(status=options[status.lower()])
    await say(ctx, "🟢 Status set to **{}**.".format(status.lower()))


def make_activity_cmd(label, builder):
    async def callback(ctx, *, text: str):
        await bot.change_presence(activity=builder(text[:128]))
        await say(ctx, "🎮 Now {} **{}**".format(label, text[:128]))
    return callback


register("Utility", "playing", make_activity_cmd("playing", lambda t: discord.Game(name=t)), "Set a 'Playing' activity.")
register("Utility", "watching", make_activity_cmd("watching", lambda t: discord.Activity(type=discord.ActivityType.watching, name=t)), "Set a 'Watching' activity.")
register("Utility", "listening", make_activity_cmd("listening to", lambda t: discord.Activity(type=discord.ActivityType.listening, name=t)), "Set a 'Listening' activity.")


@command("Utility", "clearactivity")
async def c_clearactivity(ctx):
    """Remove your custom activity."""
    await bot.change_presence(activity=None)
    await say(ctx, "🧼 Activity cleared.")


@command("Utility", "tz")
async def c_tz(ctx, *, zone: str = "UTC"):
    """Current time in a timezone. Usage: tz Europe/Stockholm"""
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(zone.strip()))
    except Exception:  # noqa: BLE001
        return await say(ctx, "❌ Unknown timezone (try `Europe/Stockholm`, `America/New_York`...).")
    await say(ctx, "🌍 {}: **{}**".format(zone.strip(), now.strftime("%Y-%m-%d %H:%M:%S %Z")))


@command("Utility", "daysuntil")
async def c_daysuntil(ctx, *, date: str):
    """Days until a date. Usage: daysuntil 2026-12-24"""
    try:
        target = parse_date(date).date()
    except ValueError as exc:
        return await say(ctx, "❌ {}".format(exc))
    days = (target - datetime.utcnow().date()).days
    await say(ctx, "📆 {} day(s) {}.".format(abs(days), "to go" if days >= 0 else "ago"))


@command("Utility", "age")
async def c_age(ctx, *, birthdate: str):
    """Age from a birth date. Usage: age 1999-05-17"""
    try:
        born = parse_date(birthdate).date()
    except ValueError as exc:
        return await say(ctx, "❌ {}".format(exc))
    days = (datetime.utcnow().date() - born).days
    await say(ctx, "🎂 {:.1f} years ({:,} days)".format(days / 365.2425, days))


@command("Utility", "weekday")
async def c_weekday(ctx, *, date: str):
    """Weekday of a date."""
    try:
        await say(ctx, "📅 " + parse_date(date).strftime("%A"))
    except ValueError as exc:
        await say(ctx, "❌ {}".format(exc))


@command("Utility", "dateadd")
async def c_dateadd(ctx, date: str, days: int):
    """Add days to a date. Usage: dateadd 2026-10-27 30"""
    try:
        result = parse_date(date) + timedelta(days=days)
    except (ValueError, OverflowError) as exc:
        return await say(ctx, "❌ {}".format(exc))
    await say(ctx, "📅 {}".format(result.strftime("%A, %Y-%m-%d")))


async def _pomodoro(ctx, work, rest):
    await asyncio.sleep(work * 60)
    await ctx.reply("🍅 Work session done - take a {}-minute break!".format(rest), mention_author=False)
    await asyncio.sleep(rest * 60)
    await ctx.reply("🍅 Break over - back to work!", mention_author=False)


@command("Utility", "pomodoro")
async def c_pomodoro(ctx, work: int = 25, rest: int = 5):
    """Start a pomodoro. Usage: pomodoro [work_min] [break_min]"""
    work, rest = max(1, min(work, 180)), max(1, min(rest, 60))
    spawn(_pomodoro(ctx, work, rest))
    await say(ctx, "🍅 Focus for {} minutes, then break for {}.".format(work, rest))


@command("Utility", "jump")
async def c_jump(ctx):
    """Get the jump link of the message you reply to."""
    ref = get_ref(ctx)
    await say(ctx, ref.jump_url if ref else "⚠️ Reply to a message.")


@command("Utility", "msgid")
async def c_msgid(ctx):
    """Get the ID of the message you reply to."""
    ref = get_ref(ctx)
    await say(ctx, "`{}`".format(ref.id) if ref else "⚠️ Reply to a message.")


@command("Utility", "raw")
async def c_raw(ctx):
    """Show the raw text of the message you reply to."""
    ref = get_ref(ctx)
    await say(ctx, codeblock(ref.content) if ref and ref.content else "⚠️ Reply to a message with text.")


@command("Utility", "firstmsg")
async def c_firstmsg(ctx):
    """Link to the first message in this channel."""
    async for msg in ctx.channel.history(limit=1, oldest_first=True):
        return await say(ctx, msg.jump_url)
    await say(ctx, "No messages found.")


@command("Utility", "ascii")
async def c_ascii(ctx, *, text: str = ""):
    """Show character codes of text (first 50 chars)."""
    text = get_text(ctx, text)
    await say(ctx, " ".join("{}={}".format(c, ord(c)) for c in text[:50]) or "⚠️ Give me text.")


@command("Utility", "unicode")
async def c_unicode(ctx, *, text: str = ""):
    """Show Unicode names of characters (first 20)."""
    text = get_text(ctx, text)
    lines = ["{} U+{:04X} {}".format(c, ord(c), unicodedata.name(c, "UNKNOWN")) for c in text[:20]]
    await say(ctx, "\n".join(lines) or "⚠️ Give me text.")


@command("Utility", "urls")
async def c_urls(ctx, *, text: str = ""):
    """Extract URLs from text or the replied message."""
    found = re.findall(r"https?://[^\s<>\"']+", get_text(ctx, text))
    await say(ctx, "\n".join(found) or "No URLs found.")


@command("Utility", "emojiurl")
async def c_emojiurl(ctx, emoji: str):
    """Get the image URL of a custom emoji."""
    match = re.fullmatch(r"<(a?):\w+:(\d+)>", emoji.strip())
    if not match:
        return await say(ctx, "⚠️ Give me a custom emoji.")
    await say(ctx, "https://cdn.discordapp.com/emojis/{}.{}".format(match[2], "gif" if match[1] else "png"))


@command("Utility", "countdown")
async def c_countdown(ctx, seconds: int = 5):
    """Edit-based countdown (max 10 seconds)."""
    seconds = max(1, min(seconds, 10))
    msg = await ctx.reply("⏳ {}".format(seconds), mention_author=False)
    for remaining in range(seconds - 1, 0, -1):
        await asyncio.sleep(1)
        await msg.edit(content="⏳ {}".format(remaining))
    await asyncio.sleep(1)
    await msg.edit(content="🚀 Go!")


@command("Utility", "quote")
async def c_quote(ctx):
    """Quote the message you reply to."""
    ref = get_ref(ctx)
    if not ref or not ref.content:
        return await say(ctx, "⚠️ Reply to a message with text.")
    quoted = "\n".join("> " + line for line in ref.content.splitlines())
    await say(ctx, "{}\n— {}, {}".format(quoted, ref.author.display_name, ref.created_at.strftime("%Y-%m-%d")))


@command("Utility", "invite")
@commands.guild_only()
@commands.has_permissions(create_instant_invite=True)
async def c_invite(ctx, hours: int = 24):
    """Create an invite link. Usage: invite [hours_valid]"""
    invite = await ctx.channel.create_invite(max_age=max(1, min(hours, 168)) * 3600)
    await say(ctx, invite.url)


# ==========================================================================
# 8) GENERATORS  (25)
# ==========================================================================
LOREM = ("lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore "
         "et dolore magna aliqua enim ad minim veniam quis nostrud exercitation ullamco laboris nisi aliquip "
         "ex ea commodo consequat").split()
ADJECTIVES = ["Swift", "Brave", "Quiet", "Clever", "Lucky", "Cosmic", "Fuzzy", "Mighty", "Sleepy", "Golden"]
NOUNS = ["Falcon", "Panda", "Comet", "Otter", "Dragon", "Pixel", "Wizard", "Lynx", "Robot", "Maple"]

GEN_TEXT_FUNCS = [
    ("sha256", "SHA-256 hash.", lambda t: hashlib.sha256(t.encode()).hexdigest()),
    ("sha1", "SHA-1 hash.", lambda t: hashlib.sha1(t.encode()).hexdigest()),
    ("md5", "MD5 hash.", lambda t: hashlib.md5(t.encode()).hexdigest()),
    ("sha512", "SHA-512 hash.", lambda t: hashlib.sha512(t.encode()).hexdigest()),
    ("crc32", "CRC32 checksum.", lambda t: format(zlib.crc32(t.encode()) & 0xFFFFFFFF, "08x")),
    ("urlencode", "URL-encode text.", lambda t: quote(t)),
    ("urldecode", "URL-decode text.", lambda t: unquote(t)),
    ("htmlescape", "Escape HTML entities.", lambda t: html.escape(t)),
    ("htmlunescape", "Unescape HTML entities.", lambda t: html.unescape(t)),
    ("jsonpretty", "Pretty-print JSON.", lambda t: codeblock(json.dumps(json.loads(t), indent=2, ensure_ascii=False), "json")),
    ("jsonmin", "Minify JSON.", lambda t: codeblock(json.dumps(json.loads(t), separators=(",", ":"), ensure_ascii=False), "json")),
]
for _name, _help, _fn in GEN_TEXT_FUNCS:
    register("Generators", _name, make_text_cmd(_fn), _help)


@command("Generators", "password")
async def c_password(ctx, length: int = 16):
    """Generate a random password (8-64). Usage: password [length]"""
    length = max(8, min(length, 64))
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*-_"
    await say(ctx, "🔐 `{}`".format("".join(secrets.choice(alphabet) for _ in range(length))))


@command("Generators", "uuid")
async def c_uuid(ctx):
    """Generate a UUID4."""
    await say(ctx, "`{}`".format(uuid.uuid4()))


@command("Generators", "randomhex")
async def c_randomhex(ctx):
    """Random hex colour."""
    await say(ctx, "#{:06x}".format(secrets.randbits(24)))


@command("Generators", "randomcolor")
async def c_randomcolor(ctx):
    """Random colour with hex and RGB."""
    r, g, b = (secrets.randbelow(256) for _ in range(3))
    await say(ctx, "🎨 `#{:02x}{:02x}{:02x}` - rgb({}, {}, {})".format(r, g, b, r, g, b))


@command("Generators", "randomnumber")
async def c_randomnumber(ctx, low: int = 1, high: int = 100):
    """Random number. Usage: randomnumber [low] [high]"""
    if low > high:
        low, high = high, low
    await say(ctx, "🎲 {}".format(random.randint(low, high)))


@command("Generators", "randomname")
async def c_randomname(ctx):
    """Random two-word name."""
    await say(ctx, "{}{}{}".format(random.choice(ADJECTIVES), random.choice(NOUNS), random.randint(10, 99)))


@command("Generators", "lorem")
async def c_lorem(ctx, words: int = 30):
    """Lorem ipsum text (max 200 words)."""
    text = " ".join(random.choice(LOREM) for _ in range(max(1, min(words, 200))))
    await say(ctx, text.capitalize() + ".")


@command("Generators", "randomstring")
async def c_randomstring(ctx, length: int = 12):
    """Random alphanumeric string."""
    alphabet = string.ascii_letters + string.digits
    await say(ctx, "`{}`".format("".join(secrets.choice(alphabet) for _ in range(max(1, min(length, 200))))))


@command("Generators", "pincode")
async def c_pin_code(ctx, digits: int = 4):
    """Random numeric PIN."""
    await say(ctx, "`{}`".format("".join(secrets.choice(string.digits) for _ in range(max(3, min(digits, 12))))))


@command("Generators", "randomip")
async def c_randomip(ctx):
    """Random IP from the reserved documentation ranges."""
    prefix = random.choice(["192.0.2", "198.51.100", "203.0.113"])
    await say(ctx, "`{}.{}`".format(prefix, random.randint(1, 254)))


@command("Generators", "randommac")
async def c_randommac(ctx):
    """Random locally-administered MAC address."""
    octets = [0x02] + [random.randint(0, 255) for _ in range(5)]
    await say(ctx, "`{}`".format(":".join("{:02x}".format(o) for o in octets)))


@command("Generators", "randomdate")
async def c_randomdate(ctx):
    """Random date between 2000 and 2030."""
    start = datetime(2000, 1, 1)
    await say(ctx, "📅 " + (start + timedelta(days=random.randint(0, 11000))).strftime("%A, %Y-%m-%d"))


@command("Generators", "shuffle")
async def c_shuffle(ctx, *, text: str):
    """Shuffle the words of a text."""
    words = text.split()
    random.shuffle(words)
    await say(ctx, " ".join(words))


@command("Generators", "randomteam")
async def c_randomteam(ctx, *, names: str):
    """Split names into two random teams. Usage: randomteam a b c d"""
    people = names.replace(",", " ").split()
    if len(people) < 2:
        return await say(ctx, "⚠️ Give at least two names.")
    random.shuffle(people)
    half = (len(people) + 1) // 2
    await say(ctx, "🅰️ **Team 1:** {}\n🅱️ **Team 2:** {}".format(", ".join(people[:half]), ", ".join(people[half:])))


# --------------------------------------------------------------------------
# Events
# --------------------------------------------------------------------------
@bot.event
async def on_ready():
    print("Logged in as {} ({})".format(bot.user, bot.user.id))
    print("Prefix: {} | {} commands in {} categories".format(PREFIX, len(bot.commands), len(REGISTRY)))


@bot.event
async def on_message(message):
    # Safety: only YOUR OWN messages can run commands.
    if message.author.id != bot.user.id:
        return
    await bot.process_commands(message)


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    if isinstance(error, commands.MissingRequiredArgument):
        text = "⚠️ Missing `{}`. Usage: `{}{} {}`".format(error.param.name, PREFIX, ctx.command.name, ctx.command.signature)
    elif isinstance(error, commands.MissingPermissions):
        text = "🚫 Your account lacks permission: {}".format(", ".join(error.missing_permissions))
    elif isinstance(error, commands.NoPrivateMessage):
        text = "⚠️ That command only works in servers."
    elif isinstance(error, commands.BadArgument):
        text = "⚠️ Bad argument: {}".format(error)
    elif isinstance(error, commands.CommandInvokeError):
        original = error.original
        if isinstance(original, discord.Forbidden):
            text = "🚫 Discord refused: missing permissions or role hierarchy."
        else:
            text = "💥 {}: {}".format(type(original).__name__, original)
    else:
        text = "⚠️ {}".format(error)
    try:
        await ctx.reply(text[:1900], mention_author=False)
    except discord.HTTPException:
        pass


def main():
    if not TOKEN:
        sys.exit("Set the DISCORD_TOKEN environment variable first.")
    bot.run(TOKEN)


if __name__ == "__main__":
    main()
