# selfbot

Command script for a Discord user account (discord.py-self).

## Run

    pip install -r requirements.txt
    export DISCORD_TOKEN="your-token"   # set as an environment variable on the host
    python selfbot.py

Never put the token in the code or in this repository.

Optional env vars: `BOT_PREFIX` (default `!`), `DATA_FILE` (default `selfbot_data.json`).
