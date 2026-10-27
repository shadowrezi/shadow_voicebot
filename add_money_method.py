from pathlib import Path
p = Path(r"C:\Users\shadowrezi\Documents\Code\jarvis\jarvis\tools.py")
d = p.read_text(encoding="utf-8")
# find marker after currency method
needle = "        if item[\"currencyCodeA\"] == demand and item[\"currencyCodeB\"] == 980:"
addition = '''        return "Monobank: rate not found."

    # ------------------------------------------------------------------ bank balance
    def _tool_money_on_card(self) -> str:
        """Balances and limits on Monobank cards (requires monobank.api_token)."""
        token = self.config.get("monobank.api_token") or ""
        if not token:
            return "Monobank token is not configured in config.json (monobank.api_token)."
        try:
            response = requests.get(
                "https://api.monobank.ua/personal/client-info",
                headers={"X-Token": token},
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            return f"Monobank error: {type(exc).__name__}: {exc}"

        currency_map = {
            980: "UAH", 978: "EUR", 840: "USD", 826: "GBP",
            124: "CAD", 985: "PLN", 156: "CNY", 398: "KZT",
        }
        accounts = []
        for acc in data.get("accounts", []):
            code = acc.get("currencyCode")
            cur = currency_map.get(code, str(code))
            bal = acc.get("balance", 0) / 100
            limit = acc.get("creditLimit", 0) / 100
            masks = acc.get("maskedPan") or []
            if masks:
                accounts.append(f"{masks[0]} {cur}: balance {bal:.2f}, limit {limit:.2f}")
            else:
                accounts.append(f"account {cur}: balance {bal:.2f}, limit {limit:.2f}")
        jars = []
        for jar in data.get("jars", []):
            code = jar.get("currencyCode")
            cur = currency_map.get(code, str(code))
            bal = jar.get("balance", 0) / 100
            goal = jar.get("goal", 0) / 100
            jars.append(f"{jar.get('title', 'jar')} {cur}: {bal:.2f}/{goal:.2f}")
        info = data.get("name") or ""
        lines = [f"Monobank {info}:".strip()]
        if accounts:
            lines.extend(accounts)
        for jar in jars:
            lines.append(f"jar {jar}")
        return " | ".join(lines)
'''
idx = d.find(needle)
if idx == -1:
    raise SystemExit("marker not found")
insert_after = d.find("\n", d.find("return \"Monobank: rate not found.\"", idx))
p.write_text(d[:insert_after] + "\n" + addition + d[insert_after:], encoding="utf-8")
print("inserted")
