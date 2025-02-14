import asyncio
from sniper import Sniper

if __name__ == "__main__":
    sniper = Sniper()
    asyncio.run(sniper.run())
