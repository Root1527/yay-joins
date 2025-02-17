import logging
import asyncio
import json
import websockets
import websockets.exceptions
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
DISCORD_WS_BASE = "wss://gateway.discord.gg/?v=10&encoding-json"
SHARELINKS_API = "https://apis.roblox.com/sharelinks/v1/resolve-link"
REFRESH_INTERVAL = 3600


class Sniper:
    def __init__(self):
        self.config = self._load_config()
        self._setup_logging()
        self.temp_links: Set[str] = set()
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
                "need|want|lf|look|stop|how|bait|snip|fak|real|pl|mem|aur|hunt|sho|sea|wait|tho|think|ago|gone|prob|try|dev|adm|or|see|cap|tot|is|us|spa|giv|get|hav|and|str|sc|br|rai|wi|san|star|null|pm|gra|pump|moon|scr|mac|do|did|jk|exchange|no|rep|dm|farm|sum|who|if|imag|pro|bot|next|post|was",
                "need|want|lf|look|stop|how|bait|ste|snip|fak|real|pl|hunt|on|sho|sea|wait|tho|gone|think|ago|prob|try|dev|adm|or|see|cap|tot|is|us|spa|giv|get|hav|and|str|sc|br|rai|wi|san|star|null|pm|gra|pump|moon|scr|mac|do|did|jk|no|rep|dm|farm|sum|who|if|imag|pro|bot|next|post|was|bae|fae",
                "need|want|lf|look|stop|how|bait|ste|snip|fak|real|pl|hunt|on|sho|sea|wait|tho|gone|think|ago|prob|try|dev|adm|or|see|cap|tot|is|us|giv|get|hav|and|str|br|rai|wi|san|star|null|pm|gra|pump|moon|scr|mac|do|did|jk|no|rep|dm|farm|sum|who|if|imag|pro|bot|next|post|was|bae|fae",
            ]
        ]
        self.word_patterns = [
            re.compile(pattern)
            for pattern in [r"jest| ob|op", r"g[litc]+h", r"d[rea]+ms"]
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
        self.roblox_session = aiohttp.ClientSession()
        self.roblox_session.cookie_jar.update_cookies(
            {".ROBLOSECURITY": self.config["Authentication"]["ROBLOSECURITY Cookie"]}
        )

    async def refresh_temp_links(self):
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            self.temp_links.clear()
            self.logger.info("Refreshed filtered link list!")

    async def _identify(self, ws):
        identify_payload = {
            "op": 2,
            "d": {
                "token": self.config["Authentication"]["Discord Token"],
                "properties": {"$os": "windows", "$browser": "chrome", "$device": "pc"}
            }
        }
        await ws.send(json.dumps(identify_payload))
        
    async def _subscribe(self, ws):
        subscription_payload = {
            "op": 14,
            "d": {
                    "guild_id": "1186570213077041233",
                    "channels_ranges": {},
                    "typing": True,
                    "threads": False,
                    "activities": False,
                    "members": [],
                    "thread_member_lists": []
                }
            }
        await ws.send(json.dumps(subscription_payload))

    async def heartbeat(self, ws, interval):
        while True:
            await asyncio.sleep(interval)
            heartbeatJSON= {
                'op':1,
                'd': 'null'
            }
            await ws.send(json.dumps(heartbeatJSON))

    async def _on_message(self, ws):
        while True:
            event = json.loads(await ws.recv())
            try:
                if event["t"] == "MESSAGE_CREATE":
                    for choice_id in self.cycle_index:
                        if (int(event["d"]["channel_id"]) == [1282543762425516083,1282542323590496277,1282542323590496277][choice_id]):
                            await self.process_message(event["d"]["content"], choice_id)
                if event['op'] == 9:
                    await self._identify(ws)
            except:
                pass

    def _should_process_message(self, message: str, choice_id: int) -> bool:
        if message in self.temp_links:
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

        if self.config["Technical"]["Using Multiple Instances"].lower() == "true":
            proc = await asyncio.create_subprocess_exec(
                adb_path, "devices", stdout=asyncio.subprocess.PIPE
            )
            output = await proc.stdout.read()
            devices = self.emu_pattern.findall(output.decode())

            for device in devices:
                shell_cmd = f"{adb_path} -s {device} shell am start -a android.intent.action.VIEW -d '{final_link}'"
                Popen(shell_cmd, shell=True)
        else:
            shell_cmd = f"{adb_path} shell am start -a android.intent.action.VIEW -d '{final_link}'"
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

        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=payload) as response:
                if response.status >= 400:
                    self.logger.error(f"Failed to send webhook: {await response.text()}")

    async def process_message(self, content: str, choice_id: int) -> None:
        try:
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

    async def run(self):
        await self.setup()
        self._refresh_task = asyncio.create_task(self.refresh_temp_links())

        jester = self.config["Toggles"]["Jester"].lower() == "true"
        glitch = self.config["Toggles"]["Glitched"].lower() == "true"
        dream = self.config["Toggles"]["Dreamspace"].lower() == "true"
        snipe_list = [jester, glitch, dream]

        self.cycle_index = [i for i, x in enumerate(snipe_list) if x]

        if not (jester or glitch or dream):
            self.logger.error("At least one option has to be True.")
            return

        system("title yay joins v1.0.0")
        system("CLS")

        self.logger.info("SNIPER STARTED")
        
        
        async with websockets.connect(DISCORD_WS_BASE, max_size=None) as ws:
            event = json.loads(await ws.recv())
            interval = event["d"]["heartbeat_interval"] / 1500
            asyncio.gather(self.heartbeat(ws, interval))
            
            await self._identify(ws)
            await self._subscribe(ws)
            await self._on_message(ws)
