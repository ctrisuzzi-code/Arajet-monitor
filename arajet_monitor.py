"""
Arajet Price Monitor — via Kayak
Rota: GRU → PUJ | 1 adulto | voo direto | só Arajet
Horários: 08h e 20h (horário de Brasília)
Notificação: Telegram + CSV local
"""

import asyncio
import csv
import os
import re
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
import httpx

# ─────────────────────────────────────────
# CONFIGURAÇÕES
# ─────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_BOT_TOKEN_AQUI")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID",   "SEU_CHAT_ID_AQUI")

SEARCHES = [
    {
        "label": "24/12 → 01/01",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2026-12-24/2027-01-01?ucs=jng4sy&sort=bestflight_a&fs=airlines%3D-X1%2CLA%3Bstops%3D0"
    },
    {
        "label": "25/12 → 01/01",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2026-12-25/2027-01-01?fs=airlines%3D-X1%2CLA%3Bstops%3D0%3BfdDir%3Dtrue&ucs=jng4sy&sort=bestflight_a"
    },
    {
        "label": "05/02 → 10/02",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2027-02-05/2027-02-10?fs=airlines%3D-X1%2CLA%3Bstops%3D0%3BfdDir%3Dtrue&ucs=jng4sy&sort=bestflight_a"
    },
    {
        "label": "05/02 → 12/02",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2027-02-05/2027-02-12?fs=airlines%3D-X1%2CLA%3Bstops%3D0%3BfdDir%3Dtrue&ucs=jng4sy&sort=bestflight_a"
    },
]

CSV_FILE = "historico_precos.csv"
MAX_RETRIES = 3
# ─────────────────────────────────────────


def extrair_precos(texto: str) -> list:
    matches = re.findall(r"R\$\s*[\d\.]+(?:,\d+)?", texto)
    prices = []
    for m in matches:
        try:
            limpo = m.replace("R$", "").strip()
            if "," in limpo:
                limpo = limpo.replace(".", "").replace(",", ".")
            else:
                limpo = limpo.replace(".", "")
            val = float(limpo)
            if val > 50:
                prices.append(val)
        except ValueError:
            continue
    return prices


async def get_price(page, url: str, label: str) -> str:
    for tentativa in range(1, MAX_RETRIES + 1):
        print(f"  [{label}] Tentativa {tentativa}/{MAX_RETRIES}...")
        try:
            await page.goto(url, timeout=90000, wait_until="domcontentloaded")
            await asyncio.sleep(12)

            for selector in ["button:has-text('Aceitar')", "button:has-text('Accept')",
                              "button:has-text('Fechar')", "[aria-label='Close']",
                              "button:has-text('OK')"]:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await asyncio.sleep(2)
                except Exception:
                    pass

            seletores = [
                "text=R$",
                "[class*='price']",
                "[class*='fare']",
                "[class*='amount']",
                "[class*='valor']",
                "[class*='Price']",
            ]
            encontrou = False
            for sel in seletores:
                try:
                    await page.wait_for_selector(sel, timeout=15000)
                    encontrou = True
                    print(f"  [{label}] Seletor encontrado: {sel}")
                    break
                except PlaywrightTimeout:
                    continue

            if not encontrou:
                print(f"  [{label}] Nenhum seletor encontrado.")
                await asyncio.sleep(5)
                continue

            conteudo = await page.inner_text("body")
            prices = extrair_precos(conteudo)

            if prices:
                valor = min(prices)
                formatado = f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                print(f"  [{label}] Preço capturado: {formatado}")
                return formatado
            else:
                print(f"  [{label}] Nenhum preço encontrado.")
                await page.screenshot(path=f"debug_{label.replace('/', '-')}_{tentativa}.png")

        except Exception as e:
            print(f"  [{label}] Erro na tentativa {tentativa}: {e}")

        await asyncio.sleep(10)

    return "N/A"


def save_to_csv(results: list):
    file_exists = os.path.exists(CSV_FILE)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data/Hora", "Trecho", "Menor Preço"])
        for r in results:
            writer.writerow([now, r["label"], r["price"]])


async def send_telegram(message: str):
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
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
            locale="pt-BR",
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        for search in SEARCHES:
            price = await get_price(page, search["url"], search["label"])
            results.append({**search, "price": price})
            await asyncio.sleep(5)

        await browser.close()

    total_na = sum(1 for r in results if r["price"] == "N/A")
    linhas = "\n".join(
        f"{'✅' if r['price'] != 'N/A' else '⚠️'} *{r['label']}* → {r['price']}"
        for r in results
    )

    rodape = "_Preços para 1 adulto em BRL | Kayak_"
    if total_na == len(results):
        rodape += "\n⚠️ _Site bloqueando. Tente novamente mais tarde._"

    message = (
        f"✈️ *Arajet Monitor | GRU → PUJ*\n"
        f"🕐 {now_str}\n"
        f"────────────────\n"
        f"{linhas}\n"
        f"────────────────\n"
        f"{rodape}"
    )

    save_to_csv(results)
    await send_telegram(message)
    print("[OK] Mensagem enviada.")


if __name__ == "__main__":
    asyncio.run(main())
