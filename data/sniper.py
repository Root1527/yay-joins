import logging
import asyncio
from os import system
from datetime import datetime
from pathlib import Path
from configparser import ConfigParser
import re
from typing import Set, Optional, List
from subprocess import Popen


import aiohttp


PLACE_ID = 15532962292
BASE_ROBLOX_URL = f"https://www.roblox.com/games/{PLACE_ID}/Sols-RNG-Eon1-1"
DISCORD_API_BASE = "https://discord.com/api/v10"
SHARELINKS_API = "https://apis.roblox.com/sharelinks/v1/resolve-link"
REFRESH_INTERVAL = 3600


class Sniper:
    def __init__(self):
        self.config = self._load_config()
        self._setup_logging()
        self.temp_links: Set[str] = set()
        self.session: Optional[aiohttp.ClientSession] = None
        self.roblox_session: Optional[aiohttp.ClientSession] = None
        self._refresh_task = None
        self.is_running = True

        self.words = ["Jester", "Glitched", "Dreamspace"]

        self.link_pattern = re.compile(
            f"https://www.roblox.com/games/{PLACE_ID}/Sols-RNG-Eon1-1\\?privateServerLinkCode="
        )
        self.link_pattern_2 = re.compile(r"https://.*&type=Server")
        self.emu_pattern = re.compile(r"emulator-[0-9]{4}")

        self.blacklists = [
            re.compile(pattern)
            for pattern in [
                "need|want|lf|look|stop|how|bait|snip|fake|real|pl|mem|aur|hunt|sho|sea|wait|tho|think|ago|gone|prob|try|dev|adm|or|see|cap|tot|is|us|spa|giv|get|hav|and|str|sc|br|rai|wi|san|star|null|pm|gra|pump|moon|scr|mac|do|did|jk|exchange|no|rep|dm|farm|sum|who|if|imag|pro|bot|next|post|was",
                "need|want|lf|look|stop|how|bait|ste|snip|fake|real|pl|hunt|on|sho|sea|wait|tho|gone|think|ago|prob|try|dev|adm|or|see|cap|tot|is|us|spa|giv|get|hav|and|str|sc|br|rai|wi|san|star|null|pm|gra|pump|moon|scr|mac|do|did|jk|no|rep|dm|farm|sum|who|if|imag|pro|bot|next|post|was",
                "need|want|lf|look|stop|how|bait|ste|snip|fake|real|pl|hunt|on|sho|sea|wait|tho|gone|think|ago|prob|try|dev|adm|or|see|cap|tot|is|us|giv|get|hav|and|str|br|rai|wi|san|star|null|pm|gra|pump|moon|scr|mac|do|did|jk|no|rep|dm|farm|sum|who|if|imag|pro|bot|next|post|was",
            ]
        ]
        self.word_patterns = [
            re.compile(pattern) for pattern in [r"jest| ob|op", r"g[litc]+h", r"d[rea]+ms"]
        ]

    def _load_config(self) -> ConfigParser:
        config = ConfigParser()
        config.read(Path(__file__).parent.parent / "config.ini")
        return config

    def _setup_logging(self):
        logging.basicConfig(
            encoding="utf-8",
            level=logging.INFO,
            format="[%(asctime)s] - %(message)s",
            datefmt="%H:%M:%S",
        )
        self.logger = logging.getLogger(__name__)

    async def setup(self):
        headers = {
            "authorization": self.config["Authentication"]["Discord Token"],
        }

        self.session = aiohttp.ClientSession(headers=headers)

        self.roblox_session = aiohttp.ClientSession()
        self.roblox_session.cookie_jar.update_cookies(
            {".ROBLOSECURITY": self.config["Authentication"]["ROBLOSECURITY Cookie"]}
        )

    async def refresh_temp_links(self):
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            self.temp_links.clear()
            self.logger.info("Refreshed filtered link list!")

    async def fetch_message(self, channel_id: int) -> List[dict]:
        try:
            async with self.session.get(
                f"{DISCORD_API_BASE}/channels/{channel_id}/messages?limit=1"
            ) as response:
                if response.status >= 400:
                    self.logger.warning(response.reason)
                    return []
                return await response.json()
        except Exception as e:
            self.logger.error(f"Error fetching messages: {str(e)}")
            return []

    def _should_process_message(self, message: str, choice_id: int) -> bool:
        if message in self.temp_links:
            return False

        if len(self.temp_links) == 0:
            self.temp_links.add(message)
            return False

        if not self.word_patterns[choice_id].search(message.lower()):
            self.temp_links.add(message)
            return False

        if self.blacklists[choice_id].search(message.lower()):
            self.temp_links.add(message)
            self.logger.info(f"Filtered message! content: {message}")
            return False

        self.temp_links.add(message)
        return True

    async def _extract_server_code(self, message: str) -> Optional[str]:
        if link_match := self.link_pattern.search(message):
            return link_match.group(0).split("LinkCode=")[-1]

        if link_match_2 := self.link_pattern_2.search(message):
            share_code = link_match_2.group(0).split("code=")[-1].split("&")[0]
            return await self._convert_link(share_code)

        return None

    async def _convert_link(self, link_id: str) -> Optional[str]:
        payload = {"linkId": link_id, "linkType": "Server"}

        async with self.roblox_session.post(SHARELINKS_API, json=payload) as response:
            if response.status == 403 and "X-CSRF-TOKEN" in response.headers:
                self.roblox_session.headers["X-CSRF-TOKEN"] = response.headers[
                    "X-CSRF-TOKEN"
                ]
                async with self.roblox_session.post(
                    SHARELINKS_API, json=payload
                ) as retry_response:
                    data = await retry_response.json()
            else:
                data = await response.json()

        if data["privateServerInviteData"]["placeId"] != PLACE_ID:
            self.logger.info("Filtered non-sols link!")
            return None

        return data["privateServerInviteData"]["linkCode"]

    async def _handle_server_join(self, choice_id: int, server_code: str):
        if self.config["Technical"]["Use LDPlayer"].lower() == "true":
            await self._join_ldplayer(server_code)
        else:
            await self._join_windows(server_code)
        self.logger.info(f"{self.words[choice_id]} link found\nyay joins")

    async def _join_ldplayer(self, server_code: str):
        final_link = f"roblox://placeID={PLACE_ID}^&linkCode={server_code}"
        adb_path = Path(self.config["Technical"]["LDPlayer Path"]) / "adb.exe"

        proc = await asyncio.create_subprocess_exec(
            adb_path, "devices", stdout=asyncio.subprocess.PIPE
        )
        output = await proc.stdout.read()
        devices = self.emu_pattern.findall(output.decode())

        for device in devices:
            shell_cmd = f"{adb_path} -s {device} shell am start -a android.intent.action.VIEW -d '{final_link}'"
            Popen(shell_cmd, shell=True)

    async def _join_windows(self, server_code: str):
        final_link = f"roblox://placeID={PLACE_ID}^&linkCode={server_code}"
        Popen(["start", final_link], shell=True)

    async def _send_webhook_notification(self, choice_id: int, server_code: str):
        webhook_url = self.config["Webhook"]["Webhook Link"]
        if not webhook_url:
            return

        colors = [11141375, 11206400, 16744703]

        embed_link = f"{BASE_ROBLOX_URL}?privateServerLinkCode={server_code}"
        payload = {
            "content": f"<@{self.config['Webhook']['Discord User ID']}>",
            "embeds": [
                {
                    "title": f'[{datetime.now().strftime("%H:%M:%S")}] {self.words[choice_id]} Link Sniped!',
                    "color": colors[choice_id],
                    "fields": [
                        {"name": f"{self.words[choice_id]} Link:", "value": embed_link}
                    ],
                    "footer": {"text": "yay joins"},
                }
            ],
        }

        async with self.session.post(webhook_url, json=payload) as response:
            if response.status >= 400:
                self.logger.error(f"Failed to send webhook: {await response.text()}")

    async def process_message(self, message: list[dict], choice_id: int) -> None:
        try:
            content = message[0]["content"]

            if not self._should_process_message(content, choice_id):
                return

            server_code = await self._extract_server_code(content)
            if not server_code:
                return
            
            self.logger.info(f"Found message! content: {content}")

            await self._handle_server_join(choice_id, server_code)
            await self._send_webhook_notification(choice_id, server_code)

        except Exception as e:
            self.logger.error(f"Error processing message: {str(e)}")

    async def process_channel(self, choice_id: int) -> None:
        channel_id = [1282543762425516083, 1282542323590496277, 1282542323590496277][
            choice_id
        ]
        message = await self.fetch_message(channel_id)

        if not message:
            return

        await self.process_message(message, choice_id)

    async def run(self):
        await self.setup()
        self._refresh_task = asyncio.create_task(self.refresh_temp_links())

        jester = self.config["Toggles"]["Jester"].lower() == "true"
        glitch = self.config["Toggles"]["Glitched"].lower() == "true"
        dream = self.config["Toggles"]["Dreamspace"].lower() == "true"
        snipe_list = [jester, glitch, dream]

        if not (jester or glitch or dream):
            self.logger.error("At least one option has to be True.")
            return

        cycle = (
            (jester and glitch and dream)
            or (jester and (glitch or dream))
            or (glitch and dream)
        )
        cycle_index = [i for i, x in enumerate(snipe_list) if x]
        x = 0

        if not cycle:
            if jester:
                choice = 0
            elif glitch:
                choice = 1
            else:
                choice = 2

        system("title yay joins v1.0.0")
        system("CLS")

        self.logger.info("SNIPER STARTED")

        while self.is_running:
            if not cycle:
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.process_channel(choice))
                    continue

            for i in cycle_index:
                choice = i
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(self.process_channel(choice))
