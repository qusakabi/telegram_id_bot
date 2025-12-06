import os
import json
import asyncio
import logging
from datetime import datetime
import aiohttp
from typing import Dict, List, Optional


# File for storing wallets
WALLETS_FILE = 'wallets.json'

# Storage for last transactions
last_transactions: Dict[str, str] = {}

# Environment variables
TONAPI_TOKEN = os.getenv('TONAPI_TOKEN')
ETHERSCAN_TOKEN = os.getenv('ETHERSCAN_TOKEN')

logger = logging.getLogger(__name__)


def load_wallets() -> Dict[str, List[Dict]]:
    """Загрузка кошельков из файла"""
    if os.path.exists(WALLETS_FILE):
        with open(WALLETS_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_wallets(wallets: Dict[str, List[Dict]]) -> None:
    """Сохранение кошельков в файл"""
    with open(WALLETS_FILE, 'w') as f:
        json.dump(wallets, f, indent=2)


async def get_ton_balance(address: str) -> Optional[float]:
    """Получение баланса TON"""
    if not TONAPI_TOKEN:
        logger.error("TONAPI_TOKEN не установлен")
        return None

    url = f"https://tonapi.io/v2/accounts/{address}"
    headers = {"Authorization": f"Bearer {TONAPI_TOKEN}"}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                logger.debug(f"TON API response status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    balance = int(data.get('balance', 0)) / 1e9
                    logger.debug(f"TON balance for {address}: {balance}")
                    return balance
                else:
                    logger.error(f"TON API error: {response.status} - {await response.text()}")
    except Exception as e:
        logger.error(f"Ошибка при получении TON баланса для {address}: {e}")
    return None


async def get_btc_balance(address: str) -> Optional[float]:
    """Получение баланса Bitcoin через blockchain.info API"""
    url = f"https://blockchain.info/q/addressbalance/{address}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    balance_satoshi = await response.text()
                    balance = int(balance_satoshi) / 1e8  # Конвертация из satoshi в BTC
                    return balance
        except:
            pass
    return None


async def get_eth_balance(address: str) -> Optional[float]:
    """Получение баланса Ethereum"""
    if not ETHERSCAN_TOKEN:
        logger.error("ETHERSCAN_TOKEN не установлен")
        return None

    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "balance",
        "address": address,
        "tag": "latest",
        "apikey": ETHERSCAN_TOKEN
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                logger.debug(f"Etherscan API response status: {response.status}")
                if response.status == 200:
                    data = await response.json()
                    if data.get('status') == '1':
                        balance = int(data.get('result', 0)) / 1e18
                        logger.debug(f"ETH balance for {address}: {balance}")
                        return balance
                    else:
                        logger.error(f"Etherscan API error: {data.get('message', 'Unknown error')}")
                else:
                    logger.error(f"Etherscan API HTTP error: {response.status}")
    except Exception as e:
        logger.error(f"Ошибка при получении ETH баланса для {address}: {e}")
    return None


async def get_usdt_balance(address: str) -> Optional[float]:
    """Получение баланса USDT (ERC-20)"""
    # USDT Contract Address на Ethereum
    usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"

    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "tokenbalance",
        "contractaddress": usdt_contract,
        "address": address,
        "tag": "latest",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    balance = int(data.get('result', 0)) / 1e6  # USDT имеет 6 decimals
                    return balance
    return None


async def get_ton_transactions(address: str) -> List[Dict]:
    """Получение последних транзакций TON"""
    url = f"https://tonapi.io/v2/accounts/{address}/events"
    headers = {"Authorization": f"Bearer {TONAPI_TOKEN}"}
    params = {"limit": 5}

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, params=params) as response:
            if response.status == 200:
                data = await response.json()
                return data.get('events', [])
    return []


async def get_btc_transactions(address: str) -> List[Dict]:
    """Получение последних транзакций Bitcoin"""
    url = f"https://blockchain.info/rawaddr/{address}?limit=5"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('txs', [])
        except:
            pass
    return []


async def get_eth_transactions(address: str) -> List[Dict]:
    """Получение последних транзакций Ethereum"""
    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "txlist",
        "address": address,
        "startblock": 0,
        "endblock": 99999999,
        "page": 1,
        "offset": 5,
        "sort": "desc",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    return data.get('result', [])
    return []


async def get_usdt_transactions(address: str) -> List[Dict]:
    """Получение последних транзакций USDT"""
    usdt_contract = "0xdac17f958d2ee523a2206206994597c13d831ec7"

    url = f"https://api.etherscan.io/api"
    params = {
        "module": "account",
        "action": "tokentx",
        "contractaddress": usdt_contract,
        "address": address,
        "page": 1,
        "offset": 5,
        "sort": "desc",
        "apikey": ETHERSCAN_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            if response.status == 200:
                data = await response.json()
                if data.get('status') == '1':
                    return data.get('result', [])
    return []


async def format_ton_transaction(event: Dict, wallet_address: str) -> Optional[str]:
    """Форматирование транзакции TON"""
    actions = event.get('actions', [])
    if not actions:
        return None

    action = actions[0]
    action_type = action.get('type', 'unknown')

    timestamp = datetime.fromtimestamp(event.get('timestamp', 0))
    msg = f"🔔 <b>TON - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    if action_type == 'TonTransfer':
        ton_transfer = action.get('TonTransfer', {})
        amount = int(ton_transfer.get('amount', 0)) / 1e9
        sender = ton_transfer.get('sender', {}).get('address', 'Unknown')
        recipient = ton_transfer.get('recipient', {}).get('address', 'Unknown')

        if recipient == wallet_address:
            msg += f"📥 <b>Входящий: +{amount:.4f} TON</b>\n"
            msg += f"От: <code>{sender[:8]}...{sender[-8:]}</code>\n"
        else:
            msg += f"📤 <b>Исходящий: -{amount:.4f} TON</b>\n"
            msg += f"Кому: <code>{recipient[:8]}...{recipient[-8:]}</code>\n"

    return msg


async def format_btc_transaction(tx: Dict, wallet_address: str) -> Optional[str]:
    """Форматирование транзакции Bitcoin"""
    timestamp = datetime.fromtimestamp(tx.get('time', 0))
    msg = f"🔔 <b>BTC - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    # Определяем направление транзакции
    inputs = tx.get('inputs', [])
    outputs = tx.get('out', [])

    is_incoming = False
    amount = 0

    for output in outputs:
        if output.get('addr') == wallet_address:
            is_incoming = True
            amount += output.get('value', 0)

    amount_btc = amount / 1e8

    if is_incoming:
        msg += f"📥 <b>Входящий: +{amount_btc:.8f} BTC</b>\n"
    else:
        msg += f"📤 <b>Исходящий: -{amount_btc:.8f} BTC</b>\n"

    tx_hash = tx.get('hash', '')
    msg += f"🔗 <code>{tx_hash[:16]}...</code>\n"

    return msg


async def format_eth_transaction(tx: Dict, wallet_address: str) -> Optional[str]:
    """Форматирование транзакции Ethereum"""
    timestamp = datetime.fromtimestamp(int(tx.get('timeStamp', 0)))
    msg = f"🔔 <b>ETH - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    amount = int(tx.get('value', 0)) / 1e18
    from_addr = tx.get('from', '').lower()
    to_addr = tx.get('to', '').lower()

    if to_addr == wallet_address.lower():
        msg += f"📥 <b>Входящий: +{amount:.6f} ETH</b>\n"
        msg += f"От: <code>{from_addr[:8]}...{from_addr[-8:]}</code>\n"
    else:
        msg += f"📤 <b>Исходящий: -{amount:.6f} ETH</b>\n"
        msg += f"Кому: <code>{to_addr[:8]}...{to_addr[-8:]}</code>\n"

    return msg


async def format_usdt_transaction(tx: Dict, wallet_address: str) -> Optional[str]:
    """Форматирование транзакции USDT"""
    timestamp = datetime.fromtimestamp(int(tx.get('timeStamp', 0)))
    msg = f"🔔 <b>USDT - Новая транзакция!</b>\n\n"
    msg += f"📅 {timestamp.strftime('%Y-%m-%d %H:%M:%S')}\n"

    amount = int(tx.get('value', 0)) / 1e6
    from_addr = tx.get('from', '').lower()
    to_addr = tx.get('to', '').lower()

    if to_addr == wallet_address.lower():
        msg += f"📥 <b>Входящий: +{amount:.2f} USDT</b>\n"
        msg += f"От: <code>{from_addr[:8]}...{from_addr[-8:]}</code>\n"
    else:
        msg += f"📤 <b>Исходящий: -{amount:.2f} USDT</b>\n"
        msg += f"Кому: <code>{to_addr[:8]}...{to_addr[-8:]}</code>\n"

    return msg


async def check_wallet_transactions(chat_id: int, wallet_address: str, coin: str, bot) -> None:
    """Проверка новых транзакций для кошелька"""
    wallet_key = f"{chat_id}_{coin}_{wallet_address}"

    try:
        if coin == "TON":
            transactions = await get_ton_transactions(wallet_address)
            if transactions:
                latest_tx_id = transactions[0].get('event_id')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_id
                    return

                if last_transactions[wallet_key] != latest_tx_id:
                    # Есть новые транзакции
                    new_txs = []
                    for tx in transactions:
                        if tx.get('event_id') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_ton_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_id

        elif coin == "BTC":
            transactions = await get_btc_transactions(wallet_address)
            if transactions:
                latest_tx_hash = transactions[0].get('hash')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_hash
                    return

                if last_transactions[wallet_key] != latest_tx_hash:
                    new_txs = []
                    for tx in transactions:
                        if tx.get('hash') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_btc_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_hash

        elif coin == "ETH":
            transactions = await get_eth_transactions(wallet_address)
            if transactions:
                latest_tx_hash = transactions[0].get('hash')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_hash
                    return

                if last_transactions[wallet_key] != latest_tx_hash:
                    new_txs = []
                    for tx in transactions:
                        if tx.get('hash') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_eth_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_hash

        elif coin == "USDT":
            transactions = await get_usdt_transactions(wallet_address)
            if transactions:
                latest_tx_hash = transactions[0].get('hash')

                if wallet_key not in last_transactions:
                    last_transactions[wallet_key] = latest_tx_hash
                    return

                if last_transactions[wallet_key] != latest_tx_hash:
                    new_txs = []
                    for tx in transactions:
                        if tx.get('hash') == last_transactions[wallet_key]:
                            break
                        new_txs.append(tx)

                    for tx in reversed(new_txs):
                        msg = await format_usdt_transaction(tx, wallet_address)
                        if msg:
                            await bot.send_message(chat_id, msg, parse_mode='HTML')

                    last_transactions[wallet_key] = latest_tx_hash

    except Exception as e:
        logger.error(f"Ошибка проверки транзакций {coin} {wallet_address}: {e}")


async def monitor_all_wallets(bot) -> None:
    """Мониторинг всех кошельков"""
    logger.info("Запуск мониторинга кошельков")
    logger.info(f"TONAPI_TOKEN: {'установлен' if TONAPI_TOKEN else 'не установлен'}")
    logger.info(f"ETHERSCAN_TOKEN: {'установлен' if ETHERSCAN_TOKEN else 'не установлен'}")

    while True:
        try:
            wallets = load_wallets()
            total_wallets = sum(len(user_wallets) for user_wallets in wallets.values())
            logger.debug(f"Проверка {total_wallets} кошельков")

            for chat_id, user_wallets in wallets.items():
                for wallet in user_wallets:
                    await check_wallet_transactions(
                        int(chat_id),
                        wallet['address'],
                        wallet['coin'],
                        bot
                    )

            await asyncio.sleep(30)  # Проверка каждые 30 секунд

        except Exception as e:
            logger.error(f"Ошибка мониторинга: {e}")
            await asyncio.sleep(30)
