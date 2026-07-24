from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from ollama import Client
from dotenv import load_dotenv
import json
import os
import traceback

load_dotenv()

app = FastAPI(title="AI Expense API")


class ExpenseRequest(BaseModel):
    text: str
    available_members: list[str]


class CalculateRequest(BaseModel):
    expenses: list[dict]
    all_members: list[str]


# ################################################################# 
# ####                    Extract Expense                       ###
# #################################################################

@app.post("/api/v1/extract-expense")
def extract_expense(request: ExpenseRequest):
    API_KEY = os.getenv("OLLAMA_API_KEY")
    client = Client(
        os.getenv("OLLAMA_HOST", "http://localhost:11434"),
        headers={"Authorization": f"Bearer {API_KEY}"}
    )

    prompt = f"""Extract expense details from this Persian text.
Available members: {request.available_members}
Text: "{request.text}"

Rules:
- payer and participants MUST be exact names from available members list
- output all in persian
- Respond with ONLY this JSON, nothing else, no explanation:
{{"description":"...","total_amount":0,"payer":"...","participants":[],"type":"group","individual_amounts":{{}}}}"""

    raw = ""
    try:
        response = client.chat(
            model=os.getenv("OLLAMA_GPT_MODEL"),
            messages=[
                {"role": "system", "content": "You only output valid JSON. No text before or after. No markdown. No explanation."},
                {"role": "user", "content": prompt}
            ],
            options={"temperature": 0}
        )

        print(f"[DEBUG] repr: {repr(response.message.content)}")

        raw = response.message.content.strip() if response.message.content else ""

        if not raw:
            raise HTTPException(
                status_code=500,
                detail=f"LLM returned empty content. Full response: {response}"
            )

        if len(raw) > 2000:
            raise HTTPException(status_code=500, detail="Model response too long, likely hallucination.")

        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()

        start = raw.find("{")
        end = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise HTTPException(status_code=500, detail=f"No JSON object found. Raw: {repr(raw)}")

        raw = raw[start:end]
        expense_data = json.loads(raw)
        return expense_data

    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"JSONDecodeError: {str(e)} | Raw: {repr(raw)}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"{type(e).__name__}: {str(e)}")


# ################################################################# 
# ####                    Calculate Balances                    ###
# #################################################################

@app.post("/api/v1/calculate")
def calculate_balances(request: CalculateRequest):

    def resolve_name(name: str) -> str:
        if not name:
            return name
        if name in request.all_members:
            return name
        for member in request.all_members:
            if name in member or member in name:
                return member
        return name

    balances = {name: 0 for name in request.all_members}
    report_lines = []

    for exp in request.expenses:
        payer = resolve_name(exp.get("payer"))
        total = exp.get("total_amount", 0)
        exp_type = exp.get("type", "group")
        participants = [resolve_name(p) for p in exp.get("participants", [])]
        description = exp.get("description", "?")
        individual_amounts = {
            resolve_name(k): v
            for k, v in exp.get("individual_amounts", {}).items()
        }

        if payer and payer not in balances:
            balances[payer] = 0
        if payer:
            balances[payer] += total

        if exp_type == "group" and participants:
            share = total / len(participants)
            for p in participants:
                if p not in balances:
                    balances[p] = 0
                balances[p] -= share
            report_lines.append(
                f"🔹 {description}: {total:,} تومان (پرداخت: {payer}) — تقسیم بین {len(participants)} نفر"
            )

        elif exp_type == "individual" and individual_amounts:
            parts = []
            for name, amount in individual_amounts.items():
                if name not in balances:
                    balances[name] = 0
                balances[name] -= amount
                parts.append(f"{name}: {int(amount):,}")
            report_lines.append(
                f"🔸 {description}: {total:,} تومان (پرداخت: {payer}) — [{' | '.join(parts)}]"
            )

        else:
            if participants:
                share = total / len(participants)
                for p in participants:
                    if p not in balances:
                        balances[p] = 0
                    balances[p] -= share
            report_lines.append(
                f"🔹 {description}: {total:,} تومان (پرداخت: {payer})"
            )

    debtors = [{"name": p, "amount": abs(b)} for p, b in balances.items() if b < -1]
    creditors = [{"name": p, "amount": b} for p, b in balances.items() if b > 1]

    debtors.sort(key=lambda x: x["amount"], reverse=True)
    creditors.sort(key=lambda x: x["amount"], reverse=True)

    plan = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        settle = min(debtors[i]["amount"], creditors[j]["amount"])
        plan.append({
            "from": debtors[i]["name"],
            "to": creditors[j]["name"],
            "amount": int(round(settle))
        })
        debtors[i]["amount"] -= settle
        creditors[j]["amount"] -= settle
        if debtors[i]["amount"] <= 1:
            i += 1
        if creditors[j]["amount"] <= 1:
            j += 1

    balance_summary = {name: int(round(b)) for name, b in balances.items()}

    return {
        "report": report_lines,
        "balances": balance_summary,
        "settlement_plan": plan
    }