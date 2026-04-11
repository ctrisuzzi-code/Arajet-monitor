"""
Arajet Price Monitor — Multi-datas
Rota: GRU → PUJ | 1 adulto
Pesquisas:
  1. 24/12/2026 → 01/01/2027
  2. 25/12/2026 → 01/01/2027
  3. 05/02/2027 → 10/02/2027
  4. 05/02/2027 → 12/02/2027
Horários: 08h e 20h (horário de Brasília)
Notificação: Telegram + CSV local
"""

import asyncio
import csv
import os
from datetime import datetime
from playwright.async_api import async_playwright
import httpx

# ─────────────────────────────────────────
# CONFIGURAÇÕES — preencha antes de rodar
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_BOT_TOKEN_AQUI")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "SEU_CHAT_ID_AQUI")

SEARCHES = [
    {"from": "2026-12-24", "to": "2027-01-01", "label": "24/12 → 01/01"},
    {"from": "2026-12-25", "to": "2027-01-01", "label": "25/12 → 01/01"},
    {"from": "2027-02-05", "to": "2027-02-10", "label": "05/02 → 10/02"},
    {"from": "2027-02-05", "to": "2027-02-12", "label": "05/02 → 12/02"},
]

BASE_URL = (
    "https://ezy.arajet.com/br/booking"
    "?origin=GRU&destination=PUJ&adt=1"
    "&currency=BRL&from={from}&to={to}"
)

CSV_FILE = "historico_precos.csv"
# ─────────────────────────────────────────


async def get_price(page, url: str) -> str:
    """Navega até a URL e captura o menor preço disponível."""
    try:
        await page.goto(url, timeout=60000, wait_until="networkidle")
        await page.wait_for_selector("text=R$", timeout=30000)

        prices_raw = await page.locator("text=/R\\$[\\d\\.]+/").all_text_contents()

        prices = []
        for p_text in prices_raw:
            cleaned = (
                p_text.replace("R$", "")
                      .replace(".", "")
                      .replace(",", ".")
                      .strip()
            )
            try:
                prices.append(float(cleaned))
            except ValueError:
                continue

        if prices:
            valor = min(prices)
            return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    except Exception as e:
        print(f"[ERRO] {url} — {e}")

    return "N/A"


def save_to_csv(results: list):
    """Salva todos os resultados da rodada no CSV histórico."""
    file_exists = os.path.exists(CSV_FILE)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data/Hora", "Trecho", "Ida", "Volta", "Menor Preço"])
        for r in results:
            writer.writerow([now, r["label"], r["from"], r["to"], r["price"]])


async def send_telegram(message: str):
    """Envia mensagem via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        })
        if resp.status_code != 200:
            print(f"[TELEGRAM ERRO] {resp.text}")


async def main():
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    print(f"[{now_str}] Iniciando consultas...")

    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        for search in SEARCHES:
            url = BASE_URL.format(**search)
            price = await get_price(page, url)
            results.append({**search, "price": price})
            print(f"  {search['label']}: {price}")
            await asyncio.sleep(3)  # pausa entre requisições

        await browser.close()

    # Monta mensagem do Telegram
    linhas = "\n".join(
        f"{'✅' if r['price'] != 'N/A' else '⚠️'} *{r['label']}* → {r['price']}"
        for r in results
    )

    message = (
        f"✈️ *Arajet Monitor | GRU → PUJ*\n"
        f"🕐 {now_str}\n"
        f"────────────────\n"
        f"{linhas}\n"
        f"────────────────\n"
        f"_Preços para 1 adulto em BRL_"
    )

    save_to_csv(results)
    await send_telegram(message)
    print("[OK] Mensagem enviada.")


if __name__ == "__main__":
    asyncio.run(main())
