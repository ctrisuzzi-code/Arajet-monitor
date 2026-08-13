"""
Monitor de Viagem — Voos + Hotel
Voos: GRU → PUJ via Kayak | 1 adulto
Hotel: Bahia Principe Aquamarine | 2 adultos
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
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN_SCL", "SEU_BOT_TOKEN_AQUI")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID_SCL",   "SEU_CHAT_ID_AQUI")

VOOS = [
    {
        "label": "24/12 → 31/12",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2026-12-24/2026-12-31?ucs=jng4sy&sort=bestflight_a&fs=airlines%3D-X1%2CLA%3Bstops%3D0"
    },
    {
        "label": "24/12 → 01/01",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2026-12-24/2027-01-01?ucs=jng4sy&sort=bestflight_a&fs=airlines%3D-X1%2CLA%3Bstops%3D0"
    },
    {
        "label": "25/12 → 31/12",
        "url": "https://www.kayak.com.br/flights/GRU-PUJ/2026-12-25/2026-12-31?fs=airlines%3D-X1%2CLA%3Bstops%3D0%3BfdDir%3Dtrue&ucs=jng4sy&sort=bestflight_a"
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

HOTEIS = [
    {
        "label": "24/12 → 31/12",
        "url": "https://pt.book.bahia-principe.com/bookcore/availability/bpgrandaqua/2026-12-24/2026-12-31/2/0/?rrc=1&adults=2&occupancies=%255B%257B%2522adults%2522%253A%25202%252C%2520%2522children%2522%253A%25200%252C%2520%2522ages%2522%253A%2520%2522%2522%257D%255D&occp=1"
    },
    {
        "label": "25/12 → 31/12",
        "url": "https://pt.book.bahia-principe.com/bookcore/availability/bpgrandaqua/2026-12-25/2026-12-31/2/0/?rrc=1&adults=2&occupancies=%255B%257B%2522adults%2522%253A%25202%252C%2520%2522children%2522%253A%25200%252C%2520%2522ages%2522%253A%2520%2522%2522%257D%255D&occp=1"
    },
    {
        "label": "25/12 → 01/01",
        "url": "https://pt.book.bahia-principe.com/bookcore/availability/bpgrandaqua/2026-12-25/2027-01-01/2/0/?rrc=1&adults=2&occupancies=%255B%257B%2522adults%2522%253A%25202%252C%2520%2522children%2522%253A%25200%252C%2520%2522ages%2522%253A%2520%2522%2522%257D%255D&occp=1"
    },
    {
        "label": "05/02 → 12/02",
        "url": "https://pt.book.bahia-principe.com/bookcore/availability/bpgrandaqua/2027-02-06/2027-02-12/2/0/?rrc=1&adults=2&occupancies=%255B%257B%2522adults%2522%253A%25202%252C%2520%2522children%2522%253A%25200%252C%2520%2522ages%2522%253A%2520%2522%2522%257D%255D&occp=1"
    },
]

CSV_FILE = "historico_precos.csv"
MAX_RETRIES = 3
# ─────────────────────────────────────────


def parse_preco_voo(texto: str) -> float | None:
    """Extrai preço de voo do texto do card — só aceita valores com R$."""
    matches = re.findall(r"R\$\s*([\d\.]+(?:,\d+)?)", texto)
    valores = []
    for m in matches:
        try:
            limpo = m.replace(".", "").replace(",", ".")
            valores.append(float(limpo))
        except ValueError:
            continue
    # Retorna o menor valor encontrado no card
    return min(valores) if valores else None


async def get_price_from_flight_card(page, url: str, label: str) -> str:
    """Captura preço do primeiro card de voo da Arajet na página."""
    for tentativa in range(1, MAX_RETRIES + 1):
        print(f"  [{label}] Tentativa {tentativa}/{MAX_RETRIES}...")
        try:
            await page.goto(url, timeout=90000, wait_until="domcontentloaded")
            await asyncio.sleep(12)

            # Fecha popups
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

            # Aguarda resultados
            try:
                await page.wait_for_selector("text=R$", timeout=20000)
            except PlaywrightTimeout:
                print(f"  [{label}] Página sem preços visíveis.")
                continue

            # Tenta capturar cards que contenham "Arajet" no texto
            preco = None
            try:
                # Busca todos os resultados de voo
                cards = await page.locator("[class*='result']").all()
                for card in cards:
                    texto_card = await card.inner_text()

                    # Ignora cards de hotel/hospedagem/anúncio
                    if any(x in texto_card.lower() for x in [
                        "noite", "hotel", "resort", "apart", "hosped",
                        "anúncio", "anuncio", "ver oferta", "search for"
                    ]):
                        continue

                    # Só processa cards com "arajet" ou com rotas GRU/PUJ
                    if not any(x in texto_card.lower() for x in ["arajet", "gru", "puj"]):
                        continue

                    val = parse_preco_voo(texto_card)
                    if val:
                        if preco is None or val < preco:
                            preco = val

            except Exception as e:
                print(f"  [{label}] Erro nos cards: {e}")

            # Fallback: pega preços da área de resultados principal
            if not preco:
                try:
                    # Pega o texto da área de resultados excluindo rodapé
                    resultado_area = page.locator("[class*='resultsList'], [class*='results-list'], main").first
                    texto_area = await resultado_area.inner_text()

                    # Remove seção de hospedagens se presente
                    if "hospedagem" in texto_area.lower():
                        texto_area = texto_area[:texto_area.lower().index("hospedagem")]

                    val = parse_preco_voo(texto_area)
                    if val:
                        preco = val
                except Exception:
                    pass

            if preco:
                formatado = f"R$ {preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                print(f"  [{label}] Preço: {formatado}")
                return formatado
            else:
                print(f"  [{label}] Preço não encontrado.")
                await page.screenshot(path=f"debug_{label.replace('/', '-')}_{tentativa}.png")

        except Exception as e:
            print(f"  [{label}] Erro: {e}")

        await asyncio.sleep(10)

    return "N/A"


async def get_hotel_price(page, url: str, label: str) -> str:
    """Captura menor preço do hotel Bahia Príncipe."""
    for tentativa in range(1, MAX_RETRIES + 1):
        print(f"  [Hotel {label}] Tentativa {tentativa}/{MAX_RETRIES}...")
        try:
            await page.goto(url, timeout=90000, wait_until="domcontentloaded")
            await asyncio.sleep(12)

            for selector in ["button:has-text('Aceitar')", "button:has-text('Accept')",
                              "button:has-text('Fechar')", "[aria-label='Close']"]:
                try:
                    btn = page.locator(selector).first
                    if await btn.is_visible(timeout=2000):
                        await btn.click()
                        await asyncio.sleep(2)
                except Exception:
                    pass

            seletores = ["text=R$", "[class*='price']", "[class*='amount']", "[class*='valor']"]
            encontrou = False
            for sel in seletores:
                try:
                    await page.wait_for_selector(sel, timeout=15000)
                    encontrou = True
                    break
                except PlaywrightTimeout:
                    continue

            if not encontrou:
                continue

            conteudo = await page.inner_text("body")

            # Padrão 1: com R$
            matches = re.findall(r"R\$\s*([\d\.]+(?:,\d+)?)", conteudo)
            valores = []
            for m in matches:
                try:
                    limpo = m.replace(".", "").replace(",", ".")
                    valores.append(float(limpo))
                except ValueError:
                    continue

            # Padrão 2: formato BR sem R$
            if not valores:
                matches2 = re.findall(r"\b\d{1,2}\.\d{3}(?:,\d{2})?\b", conteudo)
                for m in matches2:
                    try:
                        limpo = m.replace(".", "").replace(",", ".")
                        val = float(limpo)
                        if 500 < val < 100000:
                            valores.append(val)
                    except ValueError:
                        continue

            if valores:
                preco = min(valores)
                formatado = f"R$ {preco:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
                print(f"  [Hotel {label}] Preço: {formatado}")
                return formatado

        except Exception as e:
            print(f"  [Hotel {label}] Erro: {e}")

        await asyncio.sleep(10)

    return "N/A"


def save_to_csv(voos: list, hoteis: list):
    file_exists = os.path.exists(CSV_FILE)
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(["Data/Hora", "Tipo", "Trecho", "Menor Preço"])
        for r in voos:
            writer.writerow([now, "Voo", r["label"], r["price"]])
        for r in hoteis:
            writer.writerow([now, "Hotel", r["label"], r["price"]])


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

    voos_results = []
    hoteis_results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
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

        print("--- VOOS ---")
        for search in VOOS:
            price = await get_price_from_flight_card(page, search["url"], search["label"])
            voos_results.append({**search, "price": price})
            await asyncio.sleep(5)

        print("--- HOTEL ---")
        for search in HOTEIS:
            price = await get_hotel_price(page, search["url"], search["label"])
            hoteis_results.append({**search, "price": price})
            await asyncio.sleep(5)

        await browser.close()

    linhas_voos = "\n".join(
        f"{'✅' if r['price'] != 'N/A' else '⚠️'} *{r['label']}* → {r['price']}"
        for r in voos_results
    )

    linhas_hoteis = "\n".join(
        f"{'✅' if r['price'] != 'N/A' else '⚠️'} *{r['label']}* → {r['price']}"
        for r in hoteis_results
    )

    message = (
        f"✈️ *Arajet | GRU → PUJ*\n"
        f"🕐 {now_str}\n"
        f"────────────────\n"
        f"{linhas_voos}\n"
        f"────────────────\n"
        f"🏨 *Bahia Principe Aquamarine*\n"
        f"{linhas_hoteis}\n"
        f"────────────────\n"
        f"_Preços em BRL | Kayak + Bahia Principe_"
    )

    save_to_csv(voos_results, hoteis_results)
    await send_telegram(message)
    print("[OK] Mensagem enviada.")


if __name__ == "__main__":
    asyncio.run(main())
