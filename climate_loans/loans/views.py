import json
import os
import random
import datetime
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.shortcuts import render
from django.utils import timezone

from .models import Farmer, Loan, LoanFund, ClimateTrigger, LoanProduct, SimulationLog

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Blockchain: ClimateLoanManager contract interface
# ---------------------------------------------------------------------------

CONTRACT_ABI = [
    {
        "name": "requestLoan",
        "type": "function",
        "inputs": [{"name": "amount", "type": "uint256"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "name": "updateFromOracle",
        "type": "function",
        "inputs": [{"name": "result", "type": "uint256"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "name": "prequalifyFarmer",
        "type": "function",
        "inputs": [{"name": "farmer", "type": "address"}],
        "outputs": [],
        "stateMutability": "nonpayable",
    },
    {
        "name": "getReserveStatus",
        "type": "function",
        "inputs": [],
        "outputs": [
            {"name": "verified", "type": "bool"},
            {"name": "capital",  "type": "uint256"},
            {"name": "lastChecked", "type": "uint256"},
        ],
        "stateMutability": "view",
    },
    {
        "name": "droughtTriggered",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
    },
    {
        "name": "loansIssued",
        "type": "function",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
]


def _checksum(addr):
    """Checksum an address — works with both web3 v5 and v6/v7."""
    from web3 import Web3
    fn = getattr(Web3, "to_checksum_address", None) or getattr(Web3, "toChecksumAddress")
    return fn(addr)


def _raw_tx(signed):
    """Return the raw transaction bytes — works with both web3 v5 and v6/v7."""
    return getattr(signed, "raw_transaction", None) or getattr(signed, "rawTransaction")


def _get_w3():
    """Return a connected (w3, account, contract) tuple, or raise if env vars are missing."""
    from web3 import Web3

    infura_url       = os.environ.get("INFURA_URL", "")
    private_key      = os.environ.get("PRIVATE_KEY", "")
    contract_address = os.environ.get("CONTRACT_ADDRESS", "")

    if not all([infura_url, private_key, contract_address]):
        raise EnvironmentError("Blockchain env vars (INFURA_URL / PRIVATE_KEY / CONTRACT_ADDRESS) not set")

    w3 = Web3(Web3.HTTPProvider(infura_url))
    account = w3.eth.account.from_key(private_key)
    contract = w3.eth.contract(
        address=_checksum(contract_address),
        abi=CONTRACT_ABI,
    )
    return w3, account, contract


def _request_loan_on_chain(amount):
    """
    Calls contract.requestLoan(amount) on Sepolia, waits for the receipt,
    then reads back the updated state via getReserveStatus() + loansIssued().

    Returns (tx_hash_hex, contract_state_dict) on success, or (None, error_str) on failure.
    """
    try:
        w3, account, contract = _get_w3()

        print(f"\n  [chain] Building requestLoan(${amount})…")
        nonce = w3.eth.get_transaction_count(account.address)
        tx = contract.functions.requestLoan(int(amount)).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 150_000,
            "gasPrice": w3.eth.gas_price,
        })
        signed = w3.eth.account.sign_transaction(tx, account.key)
        tx_hash = w3.eth.send_raw_transaction(_raw_tx(signed))
        hex_hash = tx_hash.hex()

        print(f"  [chain] Broadcast → {hex_hash}")
        print(f"  [chain] Waiting for Sepolia block confirmation…")
        logger.info("requestLoan(%d) broadcast tx=%s — waiting for Sepolia confirmation…", amount, hex_hash)

        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
        if receipt.status == 0:
            print(f"  [chain] ❌ REVERTED — tx={hex_hash}")
            logger.error("requestLoan(%d) REVERTED tx=%s", amount, hex_hash)
            return None, "Transaction reverted by contract"

        print(f"  [chain] ✅ Confirmed — block={receipt.blockNumber} tx={hex_hash}")
        logger.info("requestLoan(%d) confirmed block=%d tx=%s", amount, receipt.blockNumber, hex_hash)

        # Read updated contract state (single source of truth)
        _, capital, last_checked = contract.functions.getReserveStatus().call()
        loans_issued = contract.functions.loansIssued().call()
        print(f"  [chain] Contract state → capital=${capital}, loans_issued={loans_issued}")

        return hex_hash, {
            "available_capital": int(capital),
            "loans_issued": int(loans_issued),
            "last_checked": int(last_checked),
        }

    except EnvironmentError as exc:
        print(f"  [chain] ⚠️  Env vars missing: {exc}")
        logger.warning("Skipping on-chain call: %s", exc)
        return None, str(exc)
    except Exception as exc:
        print(f"  [chain] 💥 Exception: {exc}")
        logger.error("requestLoan failed: %s", exc, exc_info=True)
        return None, str(exc)


def _trigger_drought_on_chain():
    """
    Calls contract.updateFromOracle(1) to set droughtTriggered = true on-chain.
    Returns tx hash hex, or None on failure.
    """
    try:
        w3, account, contract = _get_w3()
        nonce = w3.eth.get_transaction_count(account.address)
        tx = contract.functions.updateFromOracle(1).build_transaction({
            "from": account.address,
            "nonce": nonce,
            "gas": 100_000,
            "gasPrice": w3.eth.gas_price,
        })
        signed = w3.eth.account.sign_transaction(tx, account.key)
        tx_hash = w3.eth.send_raw_transaction(_raw_tx(signed))
        hex_hash = tx_hash.hex()
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=90)
        if receipt.status == 0:
            logger.error("updateFromOracle(1) reverted tx=%s", hex_hash)
            return None
        logger.info("Drought triggered on-chain block=%d tx=%s", receipt.blockNumber, hex_hash)
        return hex_hash
    except Exception as exc:
        logger.error("_trigger_drought_on_chain failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def dashboard(request):
    latest_trigger = ClimateTrigger.objects.first()
    drought_active = latest_trigger.drought if latest_trigger else False

    total_farmers = Farmer.objects.count()
    qualified_farmers = Farmer.objects.filter(qualification_status=True).count()

    loans_by_status = {
        "pending": Loan.objects.filter(status=Loan.STATUS_PENDING).count(),
        "available": Loan.objects.filter(status=Loan.STATUS_AVAILABLE).count(),
        "disbursed": Loan.objects.filter(status=Loan.STATUS_DISBURSED).count(),
        "repaid": Loan.objects.filter(status=Loan.STATUS_REPAID).count(),
    }
    total_loans = sum(loans_by_status.values())

    funds = LoanFund.objects.all()
    loan_fund = LoanFund.objects.first()
    recent_triggers = ClimateTrigger.objects.all()[:10]
    recent_loans = Loan.objects.select_related("farmer", "loan_product").order_by("-created_at")[:20]
    simulation_logs = SimulationLog.objects.order_by("-created_at")[:50]

    context = {
        "drought_active": drought_active,
        "latest_trigger": latest_trigger,
        "total_farmers": total_farmers,
        "qualified_farmers": qualified_farmers,
        "loans_by_status": loans_by_status,
        "total_loans": total_loans,
        "funds": funds,
        "loan_fund": loan_fund,
        "recent_triggers": recent_triggers,
        "recent_loans": recent_loans,
        "simulation_logs": simulation_logs,
    }
    return render(request, "loans/dashboard.html", context)


# ---------------------------------------------------------------------------
# Core logic: activate loans when drought is detected
# ---------------------------------------------------------------------------

def activate_loans_due_to_drought():
    """
    Find all pending loans belonging to pre-qualified farmers and mark them
    as available, deducting amounts from the first fund that has capital.

    Returns a list of dicts describing each activated loan.
    """
    pending_loans = Loan.objects.filter(
        status=Loan.STATUS_PENDING,
        farmer__qualification_status=True,
    ).select_related("farmer", "loan_product", "loan_fund")

    fund = LoanFund.objects.filter(available_capital__gt=0).first()
    today = datetime.date.today()
    activated_loans = []

    for loan in pending_loans:
        if fund and fund.available_capital >= loan.amount:
            fund.available_capital -= loan.amount
            loan.status = Loan.STATUS_AVAILABLE
            loan.triggered = True
            loan.start_date = today
            loan.end_date = today + datetime.timedelta(days=365)
            loan.loan_fund = fund
            loan.save()
            activated_loans.append({
                "loan_id": loan.pk,
                "farmer": loan.farmer.name,
                "amount": loan.amount,
            })
            logger.info("Loan #%s activated for farmer %s ($%.2f)", loan.pk, loan.farmer.name, loan.amount)

    if fund and activated_loans:
        fund.save()
        logger.info("LoanFund '%s' updated — remaining capital: $%.2f", fund.name, fund.available_capital)

    return activated_loans


# ---------------------------------------------------------------------------
# API: Trigger Drought (manual / parameterised)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST", "GET"])
def trigger_drought(request):
    """
    Simulate a climate trigger event.

    POST body (JSON):
        {
            "region": "Tigray",
            "rainfall": 12.5,
            "threshold": 30.0
        }

    GET (for quick testing): uses defaults — drought = True.
    """
    if request.method == "GET":
        region = request.GET.get("region", "Default Region")
        rainfall = float(request.GET.get("rainfall", 10.0))
        threshold = float(request.GET.get("threshold", 30.0))
    else:
        try:
            body = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            return JsonResponse({"error": "Invalid JSON body"}, status=400)
        region = body.get("region", "Default Region")
        rainfall = float(body.get("rainfall", 10.0))
        threshold = float(body.get("threshold", 30.0))

    is_drought = rainfall < threshold

    trigger = ClimateTrigger.objects.create(
        region=region,
        rainfall=rainfall,
        threshold=threshold,
        drought=is_drought,
        triggered_at=timezone.now(),
    )

    logger.info("Climate trigger created — region: %s, rainfall: %.1f mm, drought: %s", region, rainfall, is_drought)

    activated_loans = []
    if is_drought:
        activated_loans = activate_loans_due_to_drought()

    return JsonResponse({
        "trigger_id": trigger.pk,
        "region": region,
        "rainfall_mm": rainfall,
        "threshold_mm": threshold,
        "drought": is_drought,
        "triggered_at": trigger.triggered_at.isoformat(),
        "loans_activated": len(activated_loans),
        "activated_loans": activated_loans,
        "message": (
            f"Drought detected — {len(activated_loans)} loans activated."
            if is_drought else
            "No drought condition. No loans activated."
        ),
    })


# ---------------------------------------------------------------------------
# Fake CHIRPS data generator
# ---------------------------------------------------------------------------

# Regions modelled on real CHIRPS coverage zones (lat/lon bounding boxes)
CHIRPS_REGIONS = [
    {"name": "Tigray, Ethiopia",    "lat": 14.1,  "lon": 38.7},
    {"name": "Sahel, Niger",        "lat": 14.8,  "lon":  8.0},
    {"name": "Somali, Ethiopia",    "lat":  6.9,  "lon": 44.5},
    {"name": "Karamoja, Uganda",    "lat":  3.1,  "lon": 34.5},
    {"name": "Turkana, Kenya",      "lat":  3.5,  "lon": 36.0},
]

# Drought threshold in mm (typical CHIRPS pentadal / monthly threshold)
CHIRPS_DROUGHT_THRESHOLD_MM = 30.0


def _fake_chirps_reading():
    """
    Simulate a CHIRPS pentadal (5-day) rainfall reading.

    CHIRPS reports rainfall in mm over a 5-day window.
    In drought years the Sahel / Horn of Africa typically sees
    0–15 mm; normal seasons see 30–80 mm.

    We bias toward drought (60 % chance) so demos reliably trigger loans.
    """
    region = random.choice(CHIRPS_REGIONS)

    if random.random() < 0.6:
        # Drought scenario: very low rainfall
        rainfall = round(random.uniform(0.0, 14.9), 2)
    else:
        # Normal / wet scenario
        rainfall = round(random.uniform(30.0, 85.0), 2)

    return {
        "source": "CHIRPS v2.0 (simulated)",
        "region": region["name"],
        "latitude": region["lat"],
        "longitude": region["lon"],
        "period": "pentadal (5-day)",
        "date": datetime.date.today().isoformat(),
        "rainfall_mm": rainfall,
        "threshold_mm": CHIRPS_DROUGHT_THRESHOLD_MM,
        "drought": rainfall < CHIRPS_DROUGHT_THRESHOLD_MM,
    }


# ---------------------------------------------------------------------------
# API: Rainfall data (oracle data source)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def rainfall_data(request):
    """
    Returns a simulated CHIRPS pentadal rainfall reading.

    The response mimics the structure of a real CHIRPS data feed.
    In production, replace _fake_chirps_reading() with a live call to
    the CHIRPS FTP/API or NASA POWER.
    """
    data = _fake_chirps_reading()

    logger.info(
        "[CHIRPS] region=%s  rainfall=%.2f mm  threshold=%.1f mm  drought=%s",
        data["region"], data["rainfall_mm"], data["threshold_mm"], data["drought"],
    )

    # oracle_simulation.py expects top-level "rainfall", "threshold", "drought"
    return JsonResponse({
        **data,
        "rainfall": data["rainfall_mm"],
        "threshold": data["threshold_mm"],
    })


# ---------------------------------------------------------------------------
# API: Oracle trigger (called by the oracle simulation script)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["GET"])
def oracle_trigger(request):
    """
    Entry point for the external oracle simulation script.
    Activates loans when drought conditions are confirmed.
    """
    logger.info("Oracle trigger received — activating loans due to drought")

    activated_loans = activate_loans_due_to_drought()

    logger.info("Oracle trigger complete — %d loan(s) activated", len(activated_loans))

    return JsonResponse({
        "status": "success",
        "loans_activated": len(activated_loans),
        "activated_loans": activated_loans,
        "message": f"Oracle trigger executed — {len(activated_loans)} loan(s) activated.",
    })


# ---------------------------------------------------------------------------
# API: Simulate Loan (server-side amount generation + fund withdrawal)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST", "GET"])
def simulate_loan(request):
    """
    End-to-end loan simulation — correct on-chain order:

    1. Generate random amount ($55–$120).
    2. Check pre-conditions (drought active, fund exists, sufficient reserves).
    3. Send transaction to contract and wait for confirmed receipt.
    4. Only if contract confirms → deduct from fund (contract is source of truth).
    5. Return result to UI.
    """
    latest_trigger = ClimateTrigger.objects.first()
    drought_active = latest_trigger.drought if latest_trigger else False
    amount = random.randint(55, 120)
    fund = LoanFund.objects.first()

    print(f"\n{'='*55}")
    print(f"  FARMER REQUEST  amount=${amount}  drought={drought_active}")
    print(f"{'='*55}")

    def _log_and_respond(status, reason, tx_hash=None):
        """Persist result to SimulationLog and return the JsonResponse."""
        SimulationLog.objects.create(
            amount=amount,
            status=status,
            reason=reason,
            tx_hash=tx_hash,
            available_capital_after=fund.available_capital if fund else 0,
            loans_issued_after=fund.loans_issued if fund else 0,
        )
        return JsonResponse({
            "loan_amount": amount,
            "status": status,
            "reason": reason,
            "available_capital": fund.available_capital if fund else 0,
            "loans_issued": fund.loans_issued if fund else 0,
            "last_updated": fund.last_updated.isoformat() if fund else None,
            "tx_hash": tx_hash,
        })

    # Pre-condition: drought must be active
    if not drought_active:
        print(f"  [pre] ❌ Rejected — no active drought in DB")
        return _log_and_respond("rejected", "No active drought — contract condition not met")

    # Pre-condition: fund must exist
    if not fund:
        print(f"  [pre] ❌ Rejected — no loan fund configured")
        return _log_and_respond("rejected", "No loan fund configured")

    # Pre-condition: sufficient reserves
    if fund.available_capital < amount:
        print(f"  [pre] ❌ Rejected — insufficient reserves (have ${fund.available_capital}, need ${amount})")
        return _log_and_respond("rejected", "Insufficient reserves")

    print(f"  [pre] ✅ Pre-conditions passed — drought active, fund=${fund.available_capital}")

    # Step 1 — send requestLoan(amount) to contract, wait for Sepolia confirmation
    logger.info("simulate_loan — amount=$%d — calling contract.requestLoan…", amount)
    tx_hash, result = _request_loan_on_chain(amount)

    # Step 2 — contract response is the source of truth
    if tx_hash is None:
        error_detail = result if isinstance(result, str) else "contract rejected"
        print(f"  [loan] ❌ REJECTED — {error_detail}")
        logger.warning("simulate_loan — failed for amount=$%d: %s", amount, error_detail)
        return _log_and_respond("rejected", error_detail)

    # Step 3 — confirmed on-chain: sync Django DB from contract state
    contract_state = result if isinstance(result, dict) else None
    if contract_state:
        fund.available_capital = contract_state["available_capital"]
        fund.loans_issued = contract_state["loans_issued"]
        fund.save()
    else:
        fund.withdraw(amount)

    print(f"  [loan] ✅ APPROVED — ${amount} disbursed via mobile money")
    print(f"  [fund] capital=${fund.available_capital}  loans_issued={fund.loans_issued}")
    logger.info(
        "simulate_loan — confirmed tx=%s — capital=$%d loans_issued=%d",
        tx_hash, fund.available_capital, fund.loans_issued,
    )

    return _log_and_respond("approved", None, tx_hash=tx_hash)


# ---------------------------------------------------------------------------
# API: Request Loan (simulation layer → mirrors contract.requestLoan)
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def request_loan(request):
    """
    Simulates contract.requestLoan(amount).

    POST body (JSON): { "amount": 85 }

    Checks the primary fund for sufficient capital and deducts if approved.
    In production, replace the fund.withdraw() call with a signed web3
    transaction to the on-chain contract.
    """
    try:
        body = json.loads(request.body)
        amount = int(body.get("amount", 0))
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({"error": "Invalid JSON body"}, status=400)

    if amount <= 0:
        return JsonResponse({"error": "Amount must be a positive integer"}, status=400)

    fund = LoanFund.objects.filter(available_capital__gt=0).first()

    if not fund:
        return JsonResponse({
            "approved": False,
            "reason": "No active loan fund",
            "available_capital": 0,
        })

    approved = fund.withdraw(amount)

    if approved:
        logger.info("Loan request approved — $%d withdrawn from fund '%s' (remaining: $%d)",
                    amount, fund.name, fund.available_capital)
        return JsonResponse({
            "approved": True,
            "amount": amount,
            "fund": fund.name,
            "available_capital": fund.available_capital,
            "last_updated": fund.last_updated.isoformat(),
        })
    else:
        logger.info("Loan request rejected — insufficient reserves (requested $%d, available $%d)",
                    amount, fund.available_capital)
        return JsonResponse({
            "approved": False,
            "reason": "insufficient reserves",
            "available_capital": fund.available_capital,
        })


# ---------------------------------------------------------------------------
# API: Farmers
# ---------------------------------------------------------------------------

def farmers_list(request):
    farmers = Farmer.objects.select_related("mfi").all().values(
        "id", "name", "phone", "national_id", "bank_id",
        "location", "qualification_status", "mfi__name",
    )
    data = [
        {
            "id": f["id"],
            "name": f["name"],
            "phone": f["phone"],
            "national_id": f["national_id"],
            "bank_id": f["bank_id"],
            "location": f["location"],
            "qualified": f["qualification_status"],
            "mfi": f["mfi__name"],
        }
        for f in farmers
    ]
    return JsonResponse({"count": len(data), "farmers": data})


# ---------------------------------------------------------------------------
# API: Loans
# ---------------------------------------------------------------------------

def loans_list(request):
    status_filter = request.GET.get("status")
    qs = Loan.objects.select_related("farmer", "loan_product", "loan_fund")
    if status_filter:
        qs = qs.filter(status=status_filter)

    data = [
        {
            "id": loan.pk,
            "farmer": loan.farmer.name,
            "farmer_id": loan.farmer.pk,
            "loan_product": loan.loan_product.name,
            "amount": loan.amount,
            "status": loan.status,
            "triggered": loan.triggered,
            "start_date": loan.start_date.isoformat() if loan.start_date else None,
            "end_date": loan.end_date.isoformat() if loan.end_date else None,
            "loan_fund": loan.loan_fund.name if loan.loan_fund else None,
        }
        for loan in qs
    ]
    return JsonResponse({"count": len(data), "loans": data})


# ---------------------------------------------------------------------------
# Secret: Reset loan fund to $100,000
# ---------------------------------------------------------------------------

@csrf_exempt
@require_http_methods(["POST"])
def reset_fund(request):
    fund = LoanFund.objects.first()
    if not fund:
        return JsonResponse({"status": "error", "reason": "No fund found"}, status=404)

    fund.available_capital = 100_000
    fund.loans_issued = 0
    fund.save()

    SimulationLog.objects.all().delete()

    print("\n💰 FUND RESET — available_capital=$100,000  loans_issued=0  logs cleared\n")
    logger.info("Fund reset to $100,000 by secret button")

    return JsonResponse({
        "status": "ok",
        "available_capital": fund.available_capital,
        "loans_issued": fund.loans_issued,
    })
