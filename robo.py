
import os
import time
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

API_KEY = os.environ["API_KEY"]
CORDAX_TOKEN = os.environ["CORDAX_TOKEN"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID_TELEGRAM = os.environ["CHAT_ID_TELEGRAM"]

API_FOOTBALL = "https://v3.football.api-sports.io/fixtures"
CORDAX = "https://api.cordax.net/Fixtures"


def normalizar(nome):
    nome = unicodedata.normalize("NFKD", nome or "")
    nome = "".join(c for c in nome if not unicodedata.combining(c))
    return "".join(c.lower() for c in nome if c.isalnum())


def get_json(url, headers=None, params=None, timeout=60):
    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def api_futebol_do_dia(data):
    headers = {"x-apisports-key": API_KEY}
    dados = get_json(API_FOOTBALL, headers=headers, params={"date": data})
    jogos = []
    for j in dados.get("response", []):
        try:
            jogos.append({
                "data": data,
                "casa": j["teams"]["home"]["name"],
                "fora": j["teams"]["away"]["name"],
                "fixture_id": j["fixture"]["id"],
                "league": j["league"]["name"],
                "country": j["league"]["country"],
            })
        except Exception:
            pass
    return jogos


def cordax_jogos_do_dia():
    headers = {"Authorization": f"Bearer {CORDAX_TOKEN}"}
    dados = get_json(CORDAX, headers=headers, params={"from": "today", "to": "today"})
    return dados if isinstance(dados, list) else dados.get("response", dados.get("data", []))


def achar_cordax_por_par(cordax_jogos):
    pares = {}
    for j in cordax_jogos:
        casa = j.get("HomeTeam")
        fora = j.get("AwayTeam")
        if casa and fora:
            pares[(normalizar(casa), normalizar(fora))] = (casa, fora)
    return pares


def historico_time(nome_time):
    headers = {"Authorization": f"Bearer {CORDAX_TOKEN}"}
    dados = get_json(
        CORDAX,
        headers=headers,
        params={"team": nome_time, "status": "FT"},
        timeout=90,
    )
    return dados if isinstance(dados, list) else dados.get("response", dados.get("data", []))


def ultimos_10_casa_fora(historico, nome_time):
    alvo = normalizar(nome_time)
    validos = []
    for jogo in historico:
        try:
            casa = jogo["HomeTeam"]
            fora = jogo["AwayTeam"]
            mandante = normalizar(casa) == alvo
            visitante = normalizar(fora) == alvo
            if not (mandante or visitante):
                continue
            if jogo.get("HomeScore") is None or jogo.get("AwayScore") is None:
                continue

            data_txt = str(jogo.get("FixtureDate", ""))
            data_txt = data_txt.replace("Z", "+00:00")
            data = datetime.fromisoformat(data_txt)

            validos.append({
                "data": data,
                "gols_casa": int(jogo["HomeScore"]),
                "gols_fora": int(jogo["AwayScore"]),
                "local": "CASA" if mandante else "FORA",
            })
        except Exception:
            continue

    validos.sort(key=lambda x: x["data"], reverse=True)
    casa = [x for x in validos if x["local"] == "CASA"][:10]
    fora = [x for x in validos if x["local"] == "FORA"][:10]
    return casa, fora


def estatisticas(lista):
    total = len(lista)
    if total == 0:
        return {
            "jogos": 0, "over15": 0, "marcou": 0, "sofreu": 0,
            "media_marcados": 0, "media_sofridos": 0, "media_total": 0
        }

    over15 = marcou = sofreu = 0
    gm_total = gs_total = 0

    for j in lista:
        if j["local"] == "CASA":
            gm, gs = j["gols_casa"], j["gols_fora"]
        else:
            gm, gs = j["gols_fora"], j["gols_casa"]

        gm_total += gm
        gs_total += gs

        if gm + gs >= 2:
            over15 += 1
        if gm >= 1:
            marcou += 1
        if gs >= 1:
            sofreu += 1

    return {
        "jogos": total,
        "over15": over15,
        "marcou": marcou,
        "sofreu": sofreu,
        "media_marcados": gm_total / total,
        "media_sofridos": gs_total / total,
        "media_total": (gm_total + gs_total) / total,
    }


def analisar(jogo, historicos):
    casa, fora = jogo["casa"], jogo["fora"]
    hc = historicos[casa]
    hf = historicos[fora]

    casa10, _ = ultimos_10_casa_fora(hc, casa)
    _, fora10 = ultimos_10_casa_fora(hf, fora)

    ec = estatisticas(casa10)
    ef = estatisticas(fora10)



    score = (
        ec["over15"] * 10 + ef["over15"] * 10
        + ec["marcou"] * 4 + ef["marcou"] * 4
        + ec["sofreu"] * 3 + ef["sofreu"] * 3
        + ec["media_total"] * 5 + ef["media_total"] * 5
    )

    return {
        "data": jogo["data"],
        "casa": casa,
        "fora": fora,
        "league": jogo["league"],
        "country": jogo["country"],
        "over_casa": ec["over15"],
        "over_fora": ef["over15"],
        "marcou_casa": ec["marcou"],
        "marcou_fora": ef["marcou"],
        "sofreu_casa": ec["sofreu"],
        "sofreu_fora": ef["sofreu"],
        "media_casa": ec["media_total"],
        "media_fora": ef["media_total"],
        "score": score,
    }


def enviar_telegram(top):
    if not top:
        texto = (
            "🤖 ROBÔ DE SINAIS\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "⚠️ Nenhuma entrada aprovada hoje.\n"
            "Critério: OVER 1.5 ≥ 8/10 para casa e visitante."
        )
    else:
        texto = "🤖 ROBÔ DE SINAIS\n━━━━━━━━━━━━━━━━━━\n"
        texto += f"🎯 {len(top)} MELHOR(ES) SINAL(IS)\n\n"

        for i, r in enumerate(top, 1):
            texto += f"{i}️⃣ {r['casa']} x {r['fora']}\n"
            texto += f"🏆 {r['league']} — {r['country']}\n"
            texto += "⚽ Mercado: OVER 1.5 GOLS\n\n"
            texto += "📊 ÚLTIMOS 10 JOGOS\n"
            texto += f"🏠 {r['casa']}: {r['over_casa']}/10 Over 1.5\n"
            texto += f"✈️ {r['fora']}: {r['over_fora']}/10 Over 1.5\n"
            texto += f"⚽ Marcou: {r['marcou_casa']}/10 + {r['marcou_fora']}/10\n"
            texto += f"🛡️ Sofreu: {r['sofreu_casa']}/10 + {r['sofreu_fora']}/10\n"
            texto += f"📈 Média total: {r['media_casa']:.2f} + {r['media_fora']:.2f}\n"
            texto += f"🏆 Score: {r['score']:.1f}\n"
            texto += "━━━━━━━━━━━━━━━━━━\n\n"

        texto += "⚠️ Análise estatística. Sem garantia de resultado."

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    r = requests.post(
        url,
        data={"chat_id": CHAT_ID_TELEGRAM, "text": texto},
        timeout=30,
    )
    r.raise_for_status()
    if not r.json().get("ok"):
        raise RuntimeError(f"Telegram retornou erro: {r.text}")


def main():
    agora = datetime.now(ZoneInfo("America/Sao_Paulo"))
    data = agora.strftime("%Y-%m-%d")

    print("🤖 ROBÔ INICIADO")
    print("📅 Data:", data)

    api_jogos = api_futebol_do_dia(data)
    cordax_dia = cordax_jogos_do_dia()
    pares_cordax = achar_cordax_por_par(cordax_dia)

    # O Cordax define o universo de competições com histórico disponível;
    # o API-Football fornece a data/calendário do dia.
    times_cordax = set()
    for par in pares_cordax:
        times_cordax.update(par)

    jogos = [
        j for j in api_jogos
        if normalizar(j["casa"]) in times_cordax
        and normalizar(j["fora"]) in times_cordax
    ]

    nomes = sorted({x["casa"] for x in jogos} | {x["fora"] for x in jogos})
    historicos = {}

    for i, nome in enumerate(nomes, 1):
        print(f"📥 Histórico {i}/{len(nomes)}: {nome}")
        historicos[nome] = historico_time(nome)
        if i < len(nomes):
            # Premium Cordax: até 5 requisições/minuto.
            time.sleep(13)

    resultados = []
    for jogo in jogos:
        try:
            r = analisar(jogo, historicos)
            if r:
                resultados.append(r)
        except Exception as e:
            print("⚠️ Erro:", jogo["casa"], "x", jogo["fora"], "-", e)

    resultados.sort(key=lambda x: x["score"], reverse=True)
    top = resultados[:3]

    print("✅ Aprovados:", len(resultados))
    print("🎯 Selecionados:", len(top))

    for i, r in enumerate(top, 1):
        print(
            f"{i}. {r['casa']} x {r['fora']} | "
            f"Over 1.5 {r['over_casa']}/10 + {r['over_fora']}/10 | "
            f"Score {r['score']:.1f}"
        )

    enviar_telegram(top)
    print("📲 Telegram: enviado com sucesso.")
    print("✅ ROBÔ FINALIZADO")


if __name__ == "__main__":
    main()
